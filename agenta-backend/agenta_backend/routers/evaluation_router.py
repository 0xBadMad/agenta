import os
import random
from bson import ObjectId
from datetime import datetime
from typing import List, Optional, Dict

from fastapi.responses import JSONResponse
from fastapi import HTTPException, APIRouter, Body, Depends, status, Response

from agenta_backend.services.helpers import format_inputs, format_outputs
from agenta_backend.models.api.evaluation_model import (
    AICritiqueCreate,
    CustomEvaluationNames,
    Evaluation,
    EvaluationScenario,
    CustomEvaluationOutput,
    CustomEvaluationDetail,
    EvaluationScenarioScoreUpdate,
    EvaluationScenarioUpdate,
    ExecuteCustomEvaluationCode,
    NewEvaluation,
    DeleteEvaluation,
    EvaluationType,
    CreateCustomEvaluation,
    EvaluationUpdate,
    EvaluationWebhook,
    SimpleEvaluationOutput,
)
from agenta_backend.services.results_service import (
    fetch_average_score_for_custom_code_run,
    fetch_results_for_human_a_b_testing_evaluation,
    fetch_results_for_auto_exact_match_evaluation,
    fetch_results_for_auto_similarity_match_evaluation,
    fetch_results_for_auto_regex_test,
    fetch_results_for_auto_webhook_test,
    fetch_results_for_auto_ai_critique,
)
from agenta_backend.services.evaluation_service import (
    UpdateEvaluationScenarioError,
    evaluate_with_ai_critique,
    fetch_custom_evaluation_names,
    fetch_custom_evaluations,
    fetch_custom_evaluation_detail,
    get_evaluation_scenario_score,
    update_evaluation_scenario,
    update_evaluation_scenario_score,
    update_evaluation,
    create_custom_code_evaluation,
    execute_custom_code_evaluation,
)
from agenta_backend.services import evaluation_service
from agenta_backend.utills.common import engine, check_access_to_app
from agenta_backend.services.db_manager import query, get_user_object
from agenta_backend.models.db_models import EvaluationDB, EvaluationScenarioDB
from agenta_backend.config import settings
from agenta_backend.services import new_db_manager
from agenta_backend.models import converters

if os.environ["FEATURE_FLAG"] in ["cloud", "ee", "demo"]:
    from agenta_backend.ee.services.auth_helper import (  # noqa pylint: disable-all
        SessionContainer,
        verify_session,
    )
    from agenta_backend.ee.services.selectors import (
        get_user_and_org_id,
    )  # noqa pylint: disable-all
    from agenta_backend.services.auth_helper import (  # noqa pylint: disable-all
        SessionContainer,
        verify_session,
    )
    from agenta_backend.services.selectors import (  # noqa pylint: disable-all
        get_user_and_org_id,
    )
else:
    from agenta_backend.services.auth_helper import SessionContainer, verify_session
    from agenta_backend.services.selectors import get_user_and_org_id

router = APIRouter()


@router.post("/", response_model=SimpleEvaluationOutput)
async def create_evaluation(
    payload: NewEvaluation,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Creates a new comparison table document
    Raises:
        HTTPException: _description_
    Returns:
        _description_
    """
    try:
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        access_app = await check_access_to_app(
            user_org_data=user_org_data, app_id=payload.app_id, check_owner=False
        )
        if not access_app:
            error_msg = f"You do not have access to this app: {payload.app_id}"
            return JSONResponse(
                {"detail": error_msg},
                status_code=400,
            )
        app_ref = await new_db_manager.fetch_app_by_id(app_id=payload.app_id)

        if app_ref is None:
            raise HTTPException(status_code=404, detail="App not found")

        new_evaluation_db = await evaluation_service.create_new_evaluation(
            payload, **user_org_data
        )
        return converters.evaluation_db_to_simple_evaluation_output(new_evaluation_db)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail="columns in the test set should match the names of the inputs in the variant",
        )


@router.put("/{evaluation_id}")
async def update_evaluation_router(
    evaluation_id: str,
    update_data: EvaluationUpdate = Body(...),
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Updates an evaluation's status.

    Raises:
        HTTPException: If the columns in the test set do not match with the inputs in the variant.

    Returns:
        None: A 204 No Content status code, indicating that the update was successful.
    """
    try:
        # Get user and organization id
        user_org_data: dict = await get_user_and_org_id(stoken_session)
        await update_evaluation(evaluation_id, update_data, **user_org_data)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except KeyError:
        raise HTTPException(
            status_code=400,
            detail="columns in the test set should match the names of the inputs in the variant",
        )


@router.get(
    "/{evaluation_id}/evaluation_scenarios",
    response_model=List[EvaluationScenario],
)
async def fetch_evaluation_scenarios(
    evaluation_id: str, stoken_session: SessionContainer = Depends(verify_session)
):
    """Fetches evaluation scenarios for a given evaluation ID.

    Arguments:
        evaluation_id (str): The ID of the evaluation for which to fetch scenarios.

    Raises:
        HTTPException: If the evaluation is not found or access is denied.

    Returns:
        List[EvaluationScenario]: A list of evaluation scenarios.
    """

    user_org_data: dict = await get_user_and_org_id(stoken_session)
    eval_scenarios = await evaluation_service.fetch_evaluation_scenarios_for_evaluation(
        evaluation_id, **user_org_data
    )

    return eval_scenarios


@router.post("/{evaluation_id}/evaluation_scenario")
async def create_evaluation_scenario(
    evaluation_id: str,
    evaluation_scenario: EvaluationScenario,
    stoken_session: SessionContainer = Depends(verify_session),
):
    """Create a new evaluation scenario for a given evaluation ID.

    Raises:
        HTTPException: If evaluation not found or access denied.

    Returns:
        None: 204 No Content status code upon success.
    """
    user_org_data = await get_user_and_org_id(stoken_session)
    await evaluation_service.create_evaluation_scenario(
        evaluation_id, evaluation_scenario, **user_org_data
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{evaluation_id}/evaluation_scenario/{evaluation_scenario_id}/{evaluation_type}"
)
async def update_evaluation_scenario_router(
    evaluation_scenario_id: str,
    evaluation_type: EvaluationType,
    evaluation_scenario: EvaluationScenarioUpdate,
    stoken_session: SessionContainer = Depends(verify_session),
):
    """Updates an evaluation scenario's vote or score based on its type.

    Raises:
        HTTPException: If update fails or unauthorized.

    Returns:
        None: 204 No Content status code upon successful update.
    """
    user_org_data = await get_user_and_org_id(stoken_session)
    try:
        await update_evaluation_scenario(
            evaluation_scenario_id,
            evaluation_scenario,
            evaluation_type,
            **user_org_data,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except UpdateEvaluationScenarioError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/evaluation_scenario/ai_critique", response_model=str)
async def evaluate_ai_critique(
    payload: AICritiqueCreate,
    stoken_session: SessionContainer = Depends(verify_session),
) -> str:
    """
    Evaluate AI critique based on the given payload.

    Args:
        payload (AICritiqueCreate): The payload containing data for AI critique evaluation.
        stoken_session (SessionContainer): The session container verified by `verify_session`.

    Returns:
        str: The output of the AI critique evaluation.

    Raises:
        HTTPException: If any exception occurs during the evaluation.
    """
    try:
        # Extract data from the payload
        payload_dict = payload.dict()

        # Run AI critique evaluation
        output = evaluate_with_ai_critique(
            llm_app_prompt_template=payload_dict["llm_app_prompt_template"],
            llm_app_inputs=payload_dict["inputs"],
            correct_answer=payload_dict["correct_answer"],
            app_variant_output=payload_dict["outputs"][0]["variant_output"],
            evaluation_prompt_template=payload_dict["evaluation_prompt_template"],
            open_ai_key=payload_dict["open_ai_key"],
        )
        return output

    except Exception as e:
        raise HTTPException(400, f"Failed to evaluate AI critique: {str(e)}")


@router.get("/evaluation_scenario/{evaluation_scenario_id}/score")
async def get_evaluation_scenario_score_router(
    evaluation_scenario_id: str,
    stoken_session: SessionContainer = Depends(verify_session())
) -> Dict[str, str]:
    """
    Fetch the score of a specific evaluation scenario.

    Args:
        evaluation_scenario_id: The ID of the evaluation scenario to fetch.
        stoken_session: Session data, verified by `verify_session`.

    Returns:
        Dictionary containing the scenario ID and its score.
    """
    user_org_data = await get_user_and_org_id(stoken_session)
    return await get_evaluation_scenario_score(evaluation_scenario_id, **user_org_data)


@router.put("/evaluation_scenario/{evaluation_scenario_id}/score")
async def update_evaluation_scenario_score_router(
    evaluation_scenario_id: str,
    payload: EvaluationScenarioScoreUpdate,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Updates the score of an evaluation scenario.

    Raises:
        HTTPException: Server error if the evaluation update fails.

    Returns:
        None: 204 No Content status code upon successful update.
    """
    user_org_data = await get_user_and_org_id(stoken_session)
    try:
        await update_evaluation_scenario_score(
            evaluation_scenario_id, payload.score, **user_org_data
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/", response_model=List[Evaluation])
async def fetch_list_evaluations(
    app_name: Optional[str] = None,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """lists of all comparison tables

    Returns:
        _description_
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    user = await get_user_object(user_org_data["uid"])

    # Construct query expression builder
    query_expression = query.eq(EvaluationDB.app_name, app_name) & query.eq(
        EvaluationDB.user, user.id
    )
    evaluations = await engine.find(EvaluationDB, query_expression)
    return [
        Evaluation(
            id=str(evaluation.id),
            status=evaluation.status,
            evaluation_type=evaluation.evaluation_type,
            custom_code_evaluation_id=evaluation.custom_code_evaluation_id,
            evaluation_type_settings=evaluation.evaluation_type_settings,
            llm_app_prompt_template=evaluation.llm_app_prompt_template,
            variants=evaluation.variants,
            app_name=evaluation.app_name,
            testset=evaluation.testset,
            created_at=evaluation.created_at,
            updated_at=evaluation.updated_at,
        )
        for evaluation in evaluations
    ]


@router.get("/{evaluation_id}", response_model=Evaluation)
async def fetch_evaluation(
    evaluation_id: str,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Fetch one comparison table

    Returns:
        _description_
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    user = await get_user_object(user_org_data["uid"])

    # Construct query expression builder
    query_expression = query.eq(EvaluationDB.id, ObjectId(evaluation_id)) & query.eq(
        EvaluationDB.user, user.id
    )
    evaluation = await engine.find_one(EvaluationDB, query_expression)
    if evaluation is not None:
        return Evaluation(
            id=str(evaluation.id),
            status=evaluation.status,
            evaluation_type=evaluation.evaluation_type,
            custom_code_evaluation_id=evaluation.custom_code_evaluation_id,
            evaluation_type_settings=evaluation.evaluation_type_settings,
            llm_app_prompt_template=evaluation.llm_app_prompt_template,
            variants=evaluation.variants,
            app_name=evaluation.app_name,
            testset=evaluation.testset,
            created_at=evaluation.created_at,
            updated_at=evaluation.updated_at,
        )
    else:
        raise HTTPException(
            status_code=404,
            detail=f"dataset with id {evaluation_id} not found",
        )


@router.delete("/", response_model=List[str])
async def delete_evaluations(
    delete_evaluations: DeleteEvaluation,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """
    Delete specific comparison tables based on their unique IDs.

    Args:
    delete_evaluations (List[str]): The unique identifiers of the comparison tables to delete.

    Returns:
    A list of the deleted comparison tables' IDs.
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    user = await get_user_object(user_org_data["uid"])

    deleted_ids = []
    for evaluations_id in delete_evaluations.evaluations_ids:
        # Construct query expression builder
        query_expression = query.eq(
            EvaluationDB.id, ObjectId(evaluations_id)
        ) & query.eq(EvaluationDB.user, user.id)
        evaluation = await engine.find_one(EvaluationDB, query_expression)

        if evaluation is not None:
            await engine.delete(evaluation)
            deleted_ids.append(evaluations_id)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Comparison table {evaluations_id} not found",
            )

    return deleted_ids


@router.get("/{evaluation_id}/results")
async def fetch_results(
    evaluation_id: str,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Fetch all the results for one the comparison table

    Arguments:
        evaluation_id -- _description_

    Returns:
        _description_
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)
    user = await get_user_object(user_org_data["uid"])

    # Construct query expression builder and retrieve evaluation from database
    query_expression = query.eq(EvaluationDB.id, ObjectId(evaluation_id)) & query.eq(
        EvaluationDB.user, user.id
    )
    evaluation = await engine.find_one(EvaluationDB, query_expression)

    if evaluation.evaluation_type == EvaluationType.human_a_b_testing:
        results = await fetch_results_for_human_a_b_testing_evaluation(
            evaluation_id, evaluation.variants
        )
        # TODO: replace votes_data by results_data
        return {"votes_data": results}

    elif evaluation.evaluation_type == EvaluationType.auto_exact_match:
        results = await fetch_results_for_auto_exact_match_evaluation(
            evaluation_id, evaluation.variants
        )
        return {"scores_data": results}

    elif evaluation.evaluation_type == EvaluationType.auto_similarity_match:
        results = await fetch_results_for_auto_similarity_match_evaluation(
            evaluation_id, evaluation.variants
        )
        return {"scores_data": results}

    elif evaluation.evaluation_type == EvaluationType.auto_regex_test:
        results = await fetch_results_for_auto_regex_test(
            evaluation_id, evaluation.variants
        )
        return {"scores_data": results}

    elif evaluation.evaluation_type == EvaluationType.auto_webhook_test:
        results = await fetch_results_for_auto_webhook_test(evaluation_id)
        return {"results_data": results}

    elif evaluation.evaluation_type == EvaluationType.auto_ai_critique:
        results = await fetch_results_for_auto_ai_critique(evaluation_id)
        return {"results_data": results}

    elif evaluation.evaluation_type == EvaluationType.custom_code_run:
        results = await fetch_average_score_for_custom_code_run(evaluation_id)
        return {"avg_score": results}


@router.post("/custom_evaluation/")
async def create_custom_evaluation(
    custom_evaluation_payload: CreateCustomEvaluation,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Create evaluation with custom python code.

    Args:
        \n custom_evaluation_payload (CreateCustomEvaluation): the required payload
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)

    # create custom evaluation in database
    evaluation_id = await create_custom_code_evaluation(
        custom_evaluation_payload, **user_org_data
    )

    return JSONResponse(
        {
            "status": "success",
            "message": "Evaluation created successfully.",
            "evaluation_id": evaluation_id,
        },
        status_code=200,
    )


@router.get(
    "/custom_evaluation/list/{app_name}",
    response_model=List[CustomEvaluationOutput],
)
async def list_custom_evaluations(
    app_name: str,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """List the custom code evaluations for a given app.

    Args:
        app_name (str): the name of the app

    Returns:
        List[CustomEvaluationOutput]: a list of custom evaluation
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)

    # Fetch custom evaluations from database
    evaluations = await fetch_custom_evaluations(app_name, **user_org_data)
    return evaluations


@router.get(
    "/custom_evaluation/{id}",
    response_model=CustomEvaluationDetail,
)
async def get_custom_evaluation(
    id: str,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Get the custom code evaluation detail.

    Args:
        id (str): the id of the custom evaluation

    Returns:
        CustomEvaluationDetail: Detail of the custom evaluation
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)

    # Fetch custom evaluations from database
    evaluation = await fetch_custom_evaluation_detail(id, **user_org_data)
    return evaluation


@router.get(
    "/custom_evaluation/{app_name}/names/",
    response_model=List[CustomEvaluationNames],
)
async def get_custom_evaluation_names(
    app_name: str, stoken_session: SessionContainer = Depends(verify_session())
):
    """Get the names of custom evaluation for a given app.

    Args:
        app_name (str): the name of the app the evaluation belongs to

    Returns:
        List[CustomEvaluationNames]: the list of name of custom evaluations
    """
    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)

    custom_eval_names = await fetch_custom_evaluation_names(app_name, **user_org_data)
    return custom_eval_names


@router.post(
    "/custom_evaluation/execute/{evaluation_id}/",
)
async def execute_custom_evaluation(
    evaluation_id: str,
    payload: ExecuteCustomEvaluationCode,
    stoken_session: SessionContainer = Depends(verify_session()),
):
    """Execute a custom evaluation code.

    Args:
        evaluation_id (str): the custom evaluation id
        payload (ExecuteCustomEvaluationCode): the required payload

    Returns:
        float: the result of the evaluation custom code
    """

    # Get user and organization id
    user_org_data: dict = await get_user_and_org_id(stoken_session)

    # Execute custom code evaluation
    formatted_inputs = format_inputs(payload.inputs)
    formatted_outputs = format_outputs(payload.outputs)
    result = await execute_custom_code_evaluation(
        evaluation_id,
        payload.app_name,
        formatted_outputs[payload.variant_name],  # gets the output of the app variant
        payload.correct_answer,
        payload.variant_name,
        formatted_inputs,
        **user_org_data,
    )
    return result


@router.post("/webhook_example_fake", response_model=EvaluationWebhook)
async def webhook_example_fake():
    """Returns a fake score response for example webhook evaluation

    Returns:
        _description_
    """

    # return a random score b/w 0 and 1
    return {"score": random.random()}
