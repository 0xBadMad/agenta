import os
import uuid
import asyncio
from pathlib import Path
from typing import List, Union

from fastapi.responses import JSONResponse
from fastapi import UploadFile, APIRouter, Depends

from agenta_backend.config import settings
from aiodocker.exceptions import DockerError
from concurrent.futures import ThreadPoolExecutor
from agenta_backend.services.docker_utils import restart_container
from agenta_backend.utills.common import (
    get_app_instance,
    check_access_to_app,
    check_access_to_variant,
)
from agenta_backend.models.api.api_models import (
    Image,
    RestartAppContainer,
    Template,
    URI,
)
from agenta_backend.services.db_manager import get_templates, get_user_object
from agenta_backend.services import new_db_manager
from agenta_backend.services.container_manager import (
    build_image_job,
    get_image_details_from_docker_hub,
    pull_image_from_docker_hub,
)

if os.environ["FEATURE_FLAG"] in ["cloud", "ee", "demo"]:
    from agenta_backend.ee.services.auth_helper import (  # noqa pylint: disable-all
        SessionContainer,
        verify_session,
    )
    from agenta_backend.ee.services.selectors import (
        get_user_and_org_id,
    )  # noqa pylint: disable-all
else:
    from agenta_backend.services.auth_helper import (
        SessionContainer,
        verify_session,
    )
    from agenta_backend.services.selectors import get_user_and_org_id
import logging

logger = logging.getLogger(__name__)

logger.setLevel(logging.DEBUG)

router = APIRouter()


@router.post("/build_image/")
async def build_image(
    app_id: str,
    app_name: str,
    variant_name: str,
    tar_file: UploadFile,
    organization_id: str = None,
    stoken_session: SessionContainer = Depends(verify_session()),
) -> Image:
    """Takes a tar file and builds a docker image from it

    Arguments:
        app_id -- The ID of the app
        app_name -- The `app_name` parameter is a string that represents the name of \
            the application for which the docker image is being built
        variant_name -- The `variant_name` parameter is a string that represents the \
            name or type of the variant for which the docker image is being built.
        tar_file -- The `tar_file` parameter is of type `UploadFile`. It represents the \
            uploaded tar file that will be used to build the Docker image

    Returns:
        an object of type `Image`.
    """

    # Get user and org id
    kwargs: dict = await get_user_and_org_id(stoken_session)

    # Check app access
    if organization_id is None:
        app_db = await new_db_manager.fetch_app_by_id(app_id)
        organization_id = str(app_db.organization_id.id)
        app_access = await check_access_to_app(kwargs, app_id=app_id, check_owner=True)
    else:
        app_access = await check_access_to_app(kwargs, app_id=app_id)

    if not app_access:
        error_msg = f"You do not have access to this app: {app_name}"
        return JSONResponse(
            {"detail": error_msg},
            status_code=400,
        )

    # Get event loop
    loop = asyncio.get_event_loop()

    # Create a ThreadPoolExecutor for running threads
    thread_pool = ThreadPoolExecutor(max_workers=4)

    # Create a unique temporary directory for each upload
    temp_dir = Path(f"/tmp/{uuid.uuid4()}")
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded file to the temporary directory
    tar_path = temp_dir / tar_file.filename
    with tar_path.open("wb") as buffer:
        buffer.write(await tar_file.read())

    image_name = f"agentaai/{app_name.lower()}_{variant_name.lower()}:latest"

    # Use the thread pool to run the build_image_job function in a separate thread
    future = loop.run_in_executor(
        thread_pool,
        build_image_job,
        *(
            app_name,
            variant_name,
            organization_id,
            tar_path,
            image_name,
            temp_dir,
        ),
    )

    # Return immediately while the image build is in progress
    image_result = await asyncio.wrap_future(future)
    return image_result


@router.post("/restart_container/")
async def restart_docker_container(
    payload: RestartAppContainer,
    stoken_session: SessionContainer = Depends(verify_session()),
) -> dict:
    """Restart docker container.

    Args:
        payload (RestartAppContainer) -- the required data (app_name and variant_name)
    """
    logger.debug(f"Restarting container for variant {payload.variant_id}")
    # Get user and org id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    access = check_access_to_variant(
        kwargs=user_org_data, variant_id=payload.variant_id
    )
    if not access:
        error_msg = f"You do not have access to this variant: {payload.variant_id}"
        return JSONResponse(
            {"detail": error_msg},
            status_code=400,
        )
    app_variant_db = await new_db_manager.fetch_app_variant_by_id(
        app_variant_id=payload.variant_id
    )
    if app_variant_db is None:
        error_msg = f"Variant with id {payload.variant_id} does not exist"
        return JSONResponse(
            {"detail": error_msg},
            status_code=400,
        )
    try:
        user_backend_container_name = f"{app_variant_db.app_id.app_name}-{app_variant_db.variant_name}-{str(app_variant_db.organization_id.id)}"
        logger.debug(f"Restarting container with id: {user_backend_container_name}")
        restart_container(user_backend_container_name)
        return {"message": "Please wait a moment. The container is now restarting."}
    except Exception as ex:
        return JSONResponse({"message": str(ex)}, status_code=500)


@router.get("/templates/")
async def container_templates(
    stoken_session: SessionContainer = Depends(verify_session()),
) -> Union[List[Template], str]:
    """Returns a list of container templates.

    Returns:
        a list of `Template` objects.
    """
    templates = await get_templates()
    return templates


@router.get("/templates/{image_name}/images/")
async def pull_image(
    image_name: str,
    stoken_session: SessionContainer = Depends(verify_session()),
) -> dict:
    """Pulls an image from Docker Hub using the provided configuration

    Arguments:
        image_name -- The name of the image to be pulled

    Returns:
        -- a JSON response with the image tag name and image ID
        -- a JSON response with the pull_image exception error
    """
    # Get docker hub config
    repo_owner = settings.docker_hub_repo_owner
    repo_name = settings.docker_hub_repo_name

    # Pull image from docker hub with provided config
    try:
        image_res = await pull_image_from_docker_hub(
            f"{repo_owner}/{repo_name}", image_name
        )
    except DockerError as ext:
        return JSONResponse(
            {"message": "Image with tag does not exist", "meta": str(ext)}, 404
        )

    # Get data from image response
    image_tag_name = image_res[0]["id"]
    image_id = await get_image_details_from_docker_hub(
        repo_owner, repo_name, image_tag_name
    )
    return JSONResponse({"image_tag": image_tag_name, "image_id": image_id}, 200)


@router.get("/container_url/")
async def construct_app_container_url(
    variant_id: str,
    stoken_session: SessionContainer = Depends(verify_session()),
) -> URI:
    """Construct and return the app container url path.

    Arguments:
        app_name -- The name of app to construct the container url path
        variant_name -- The  variant name of the app to construct the container url path
        stoken_session (SessionContainer) -- the user session.

    Returns:
        URI -- the url path of the container
    """

    # Get user and org id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    access = check_access_to_variant(kwargs=user_org_data, variant_id=variant_id)
    if access is False:
        error_msg = f"You do not have access to this variant: {variant_id}"
        return JSONResponse(
            {"detail": error_msg},
            status_code=400,
        )
    app_variant_db = await new_db_manager.fetch_app_variant_by_id(
        app_variant_id=variant_id
    )
    if app_variant_db is None:
        error_msg = f"Variant with id {variant_id} does not exist"
        return JSONResponse(
            {"detail": error_msg},
            status_code=400,
        )
    organization_id = str(app_variant_db.organization_id.id)
    app_name = app_variant_db.app_id.app_name
    variant_name = app_variant_db.variant_name
    # Set organization backend url path and container name
    org_backend_url_path = f"{organization_id}/{app_name}/{variant_name}"
    return URI(uri=f"{org_backend_url_path}")
