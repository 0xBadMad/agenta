import os
import logging
from docker.errors import DockerException
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from agenta_backend.config import settings
from typing import Any, List, Optional, Union
from fastapi import APIRouter, HTTPException, Depends
from agenta_backend.services.selectors import get_user_own_org
from agenta_backend.services import (
    app_manager,
    docker_utils,
    db_manager,
)
from agenta_backend.utils.common import (
    check_access_to_app,
    get_app_instance,
    check_user_org_access,
    check_access_to_variant,
)
from agenta_backend.models.api.api_models import (
    URI,
    App,
    RemoveApp,
    AppOutput,
    CreateApp,
    CreateAppOutput,
    AppVariant,
    Image,
    DockerEnvVars,
    CreateAppVariant,
    AddVariantFromPreviousPayload,
    AppVariantOutput,
    Variant,
    UpdateVariantParameterPayload,
    AddVariantFromImagePayload,
    AddVariantFromBasePayload,
    EnvironmentOutput,
)
from agenta_backend.models import converters

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

router = APIRouter()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@router.post("/{variant_id}/from-previous/")
async def add_variant_from_previous(
    variant_id: str,
    payload: AddVariantFromPreviousPayload,
    stoken_session: SessionContainer = Depends(verify_session()),
) -> AppVariantOutput:
    """Add a variant to the server based on a previous variant.

    Arguments:
        app_variant -- AppVariant to add
        previous_app_variant -- Previous AppVariant to use as a base
        parameters -- parameters for the variant

    Raises:
        HTTPException: If there is a problem adding the app variant
    """

    try:
        app_variant_db = await db_manager.fetch_app_variant_by_id(
            variant_id
        )
        if app_variant_db is None:
            raise HTTPException(
                status_code=500,
                detail="Previous app variant not found",
            )
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        access = await check_user_org_access(
            user_org_data, app_variant_db.organization_id.id
        )
        if not access:
            raise HTTPException(
                status_code=500,
                detail="You do not have permission to access this app variant",
            )
        db_app_variant = await db_manager.add_variant_based_on_previous(
            previous_app_variant=app_variant_db,
            new_variant_name=payload.new_variant_name,
            parameters=payload.parameters,
            **user_org_data,
        )
        return converters.app_variant_db_to_output(db_app_variant)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/from-base/")
async def add_variant_from_base(
    payload: AddVariantFromBasePayload,
    stoken_session: SessionContainer = Depends(verify_session),
) -> Union[AppVariantOutput, Any]:
    """Add a new variant based on an existing one.

    Args:
        payload (AddVariantFromBasePayload): Payload containing base variant ID, new variant name, and parameters.
        stoken_session (SessionContainer, optional): Session container. Defaults to result of verify_session().

    Raises:
        HTTPException: Raised if the variant could not be added or accessed.

    Returns:
        Union[AppVariantOutput, Any]: New variant details or exception.
    """
    try:
        logger.debug("Initiating process to add a variant based on a previous one.")
        logger.debug(f"Received payload: {payload}")

        # Find the previous variant in the database
        app_variant_db = await db_manager.find_previous_variant_from_base_id(
            payload.base_id
        )
        if app_variant_db is None:
            logger.error("Failed to find the previous app variant in the database.")
            raise HTTPException(
                status_code=500, detail="Previous app variant not found"
            )
        logger.debug(f"Located previous variant: {app_variant_db}")

        # Get user and organization data
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        logger.debug(f"Retrieved user and organization data: {user_org_data}")

        # Check user access permissions
        access = await check_user_org_access(
            user_org_data, app_variant_db.organization_id.id
        )
        if not access:
            logger.error(
                "User does not have the required permissions to access this app variant."
            )
            raise HTTPException(
                status_code=500,
                detail="You do not have permission to access this app variant",
            )
        logger.debug("User has required permissions to access this app variant.")

        # Add new variant based on the previous one
        db_app_variant = await db_manager.add_variant_based_on_previous(
            previous_app_variant=app_variant_db,
            new_variant_name=payload.new_variant_name,
            parameters=payload.parameters,
            **user_org_data,
        )
        logger.debug(f"Successfully added new variant: {db_app_variant}")

        return converters.app_variant_db_to_output(db_app_variant)
    except Exception as e:
        logger.error(f"An exception occurred while adding the new variant: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{variant_id}")
async def remove_variant(
    variant_id: str,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Remove a variant from the server.
    In the case it's the last variant using the image, stop the container and remove the image.

    Arguments:
        app_variant -- AppVariant to remove

    Raises:
        HTTPException: If there is a problem removing the app variant
    """
    try:
        user_org_data: dict = await get_user_and_org_id(stoken_session)

        # Check app access

        access_app = await check_access_to_variant(
            user_org_data, variant_id=variant_id, check_owner=True
        )

        if not access_app:
            error_msg = f"You do not have permission to delete app variant: {variant_id}"
            logger.error(error_msg)
            return JSONResponse(
                {"detail": error_msg},
                status_code=400,
            )
        else:
            await app_manager.remove_app_variant(
                app_variant_id=variant_id, **user_org_data
            )
    except DockerException as e:
        detail = f"Docker error while trying to remove the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        detail = f"Unexpected error while trying to remove the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.put("/{variant_id}/parameters/")
async def update_variant_parameters(
    variant_id: str,
    payload: UpdateVariantParameterPayload,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Updates the parameters for an app variant

    Arguments:
        app_variant -- Appvariant to update
    """
    try:
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        access_variant = await check_access_to_variant(
            user_org_data=user_org_data, variant_id=variant_id
        )

        if not access_variant:
            error_msg = f"You do not have permission to update app variant: {variant_id}"
            logger.error(error_msg)
            return JSONResponse(
                {"detail": error_msg},
                status_code=400,
            )
        else:
            await app_manager.update_variant_parameters(
                app_variant_id=variant_id,
                parameters=payload.parameters,
                **user_org_data,
            )
    except ValueError as e:
        detail = f"Error while trying to update the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        detail = f"Unexpected error while trying to update the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.put("/image/")  # TODO: Refactor to use the variant_id instead of the name
async def update_variant_image(
    app_variant: AppVariant,
    image: Image,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Updates the image used in an app variant

    Arguments:
        app_variant -- the app variant to update
        image -- the image information
    """

    try:
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        if app_variant.organization_id is None:
            app_instance = await get_app_instance(
                app_variant.app_id, app_variant.variant_name
            )
            app_variant.organization_id = str(app_instance.organization_id.id)

        access_app = await check_access_to_app(
            user_org_data, app_id=app_variant.app_id, check_owner=True
        )
        if not access_app:
            error_msg = "You do not have permission to make an update"
            logger.error(error_msg)
            return JSONResponse(
                {"detail": error_msg},
                status_code=400,
            )
        else:
            await app_manager.update_variant_image(app_variant, image, **user_org_data)
    except ValueError as e:
        detail = f"Error while trying to update the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)
    except DockerException as e:
        detail = f"Docker error while trying to update the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        detail = f"Unexpected error while trying to update the app variant: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)
