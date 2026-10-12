"""Workflow 模板管理 API:列表/保存/删除/默认模板/从 ComfyUI 用户工作流导入。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import workflow_template_service
from app.services.workflow_template_service import TemplateError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _bad_request(exc: TemplateError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_templates():
    return {"templates": workflow_template_service.list_templates(), "default": workflow_template_service.get_default()}


@router.get("/user-sources")
async def user_sources():
    return {"sources": workflow_template_service.list_user_sources()}


@router.post("/convert")
async def convert(req: ConvertRequest):
    try:
        return await workflow_template_service.convert_user_workflow(req.filename)
    except TemplateError as exc:
        raise _bad_request(exc) from exc


@router.post("")
async def save(req: SaveRequest):
    try:
        result = workflow_template_service.save_template(req.name, req.workflow_api, req.map_yaml)
    except TemplateError as exc:
        raise _bad_request(exc) from exc
    return {"name": req.name, **result}


@router.put("/default")
async def put_default(req: DefaultRequest):
    try:
        return workflow_template_service.set_default(req.name)
    except TemplateError as exc:
        raise _bad_request(exc) from exc


@router.delete("/{name}")
async def remove(name: str):
    try:
        return workflow_template_service.delete_template(name)
    except TemplateError as exc:
        raise _bad_request(exc) from exc


class ConvertRequest(BaseModel):
    filename: str


class SaveRequest(BaseModel):
    name: str
    workflow_api: dict
    map_yaml: str


class DefaultRequest(BaseModel):
    name: str
