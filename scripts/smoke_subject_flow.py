#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体纠正链路冒烟测试（依赖本地运行的后端服务）。

用法: uv run python scripts/smoke_subject_flow.py [--base http://127.0.0.1:8010]
测试数据全部使用 _smk 后缀命名，结束后自动清理。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from sqlalchemy import text

from imgtag.db.database import async_session_maker

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


async def db_fetch_one(sql: str, **params):
    async with async_session_maker() as s:
        return (await s.execute(text(sql), params)).first()


async def db_exec_returning(sql: str, **params):
    """执行写语句并提交，返回第一行。"""
    async with async_session_maker() as s:
        row = (await s.execute(text(sql), params)).first()
        await s.commit()
        return row


async def db_exec(sql: str, **params) -> None:
    async with async_session_maker() as s:
        await s.execute(text(sql), params)
        await s.commit()


async def main(base: str) -> int:
    image_id: int | None = None
    tag_ids: list[int] = []
    subject_ids: list[int] = []

    async with httpx.AsyncClient(base_url=base, timeout=120) as client:
        # ---------- 登录 ----------
        r = await client.post("/auth/login", json={"username": "admin", "password": "admin123"})
        if r.status_code != 200:
            print(f"管理员登录失败（{r.status_code}）: {r.text[:200]}")
            print("请确认默认管理员账号可用，或修改脚本中的凭据。")
            return 1
        token = r.json().get("access_token") or r.json().get("token")
        auth = {"Authorization": f"Bearer {token}"}
        print("管理员登录成功")

        try:
            # ---------- 权限：词典需登录 ----------
            r = await client.get("/subjects/")
            check("匿名访问主体词典返回 401", r.status_code == 401, f"got {r.status_code}")

            r = await client.get("/subjects/", headers=auth)
            check("登录后可访问主体词典", r.status_code == 200, f"got {r.status_code}")

            # ---------- 准备标签 ----------
            async def create_tag(name: str, level: int) -> int:
                resp = await client.post(
                    "/tags/", params={"name": name, "level": level}, headers=auth
                )
                assert resp.status_code == 200, f"创建标签失败: {resp.status_code} {resp.text[:200]}"
                return int(resp.json()["id"])

            cat_id = await create_tag("冒烟测试分类_smk", 0)
            tag_a = await create_tag("冒烟测试主体A_smk", 2)
            tag_b = await create_tag("冒烟测试主体B_smk", 2)
            tag_ids.extend([tag_a, tag_b, cat_id])
            print(f"测试标签就绪: cat={cat_id}, A={tag_a}, B={tag_b}")

            # ---------- 创建主体 ----------
            r = await client.post(
                "/subjects/",
                json={"category_tag_id": cat_id, "primary_tag_id": tag_a},
                headers=auth,
            )
            check("创建主体A成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
            subject_a = int(r.json()["id"])
            subject_ids.append(subject_a)
            check("主体A名称取自主名称标签", r.json()["name"] == "冒烟测试主体A_smk", r.json()["name"])

            r = await client.post(
                "/subjects/",
                json={"category_tag_id": cat_id, "primary_tag_id": tag_a},
                headers=auth,
            )
            check("重复占用主名称标签返回 409", r.status_code == 409, f"got {r.status_code}")

            r = await client.post(
                "/subjects/",
                json={"category_tag_id": cat_id, "primary_tag_id": tag_b},
                headers=auth,
            )
            check("创建主体B成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
            subject_b = int(r.json()["id"])
            subject_ids.append(subject_b)

            # ---------- 准备测试图片 ----------
            row = await db_exec_returning(
                "INSERT INTO images (file_type, description, is_public) "
                "VALUES ('jpg', '冒烟测试描述_smk', true) RETURNING id"
            )
            image_id = int(row[0])
            print(f"测试图片就绪: image_id={image_id}")

            # ---------- 设置主主体（含样本登记） ----------
            r = await client.put(
                f"/images/{image_id}/subjects/primary",
                json={"subject_id": subject_a, "confidence": 0.88, "add_sample": True},
                headers=auth,
            )
            check("设置主主体A成功", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
            assert r.status_code == 200, "主链路失败，终止后续步骤"
            body = r.json()
            check("assignment.changed 为 true", body["assignment"].get("changed") is True, str(body))
            check("触发了向量重建", body.get("rebuild_enqueued") is True, str(body))

            r = await client.get(f"/images/{image_id}", headers=auth)
            data = r.json()
            primary = next((s for s in data.get("subjects", []) if s["is_primary"]), None)
            check("图片详情返回主主体A", bool(primary and primary["subject_id"] == subject_a), str(data.get("subjects")))
            tag_names = [t["name"] for t in data.get("tags", [])]
            check("主体A标签已同步到图片", "冒烟测试主体A_smk" in tag_names, str(tag_names))

            row = await db_fetch_one(
                "SELECT embedding IS NULL, embedding_model FROM subject_samples "
                "WHERE subject_id = :sid ORDER BY id DESC LIMIT 1",
                sid=subject_a,
            )
            check("样本为引用记录（无向量, model=reference）", bool(row and row[0] and row[1] == "reference"), str(row))

            # ---------- 幂等重设 ----------
            r = await client.put(
                f"/images/{image_id}/subjects/primary",
                json={"subject_id": subject_a},
                headers=auth,
            )
            row = await db_fetch_one(
                "SELECT count(*) FROM image_subjects WHERE image_id = :iid", iid=image_id
            )
            check("重复设置幂等（仅一条记录）", r.status_code == 200 and int(row[0]) == 1, f"{r.status_code}, rows={row[0]}")

            # ---------- 标签联动保护 ----------
            r = await client.delete(f"/tags/id/{tag_a}", headers=auth)
            check("删除被主体引用的标签被拦截(400)", r.status_code == 400 and "主体" in r.text, f"{r.status_code} {r.text[:150]}")

            r = await client.put(
                f"/tags/id/{tag_a}", json={"name": "冒烟测试主体A改_smk"}, headers=auth
            )
            check("标签改名成功", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
            row = await db_fetch_one("SELECT name FROM subjects WHERE id = :sid", sid=subject_a)
            check("主体名称随标签改名同步", bool(row and row[0] == "冒烟测试主体A改_smk"), str(row))

            # ---------- 切换主体：旧标签移除、新标签挂接 ----------
            r = await client.put(
                f"/images/{image_id}/subjects/primary",
                json={"subject_id": subject_b},
                headers=auth,
            )
            check("切换主主体为B成功", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
            r = await client.get(f"/images/{image_id}", headers=auth)
            data = r.json()
            tag_names = [t["name"] for t in data.get("tags", [])]
            primary = next((s for s in data.get("subjects", []) if s["is_primary"]), None)
            check("主主体已切换为B", bool(primary and primary["subject_id"] == subject_b), str(data.get("subjects")))
            check("旧主体标签已移除", "冒烟测试主体A改_smk" not in tag_names, str(tag_names))
            check("新主体标签已挂接", "冒烟测试主体B_smk" in tag_names, str(tag_names))

            # ---------- 强制重新分析入队 ----------
            r = await client.put(
                f"/images/{image_id}/subjects/primary",
                json={"subject_id": subject_b, "reanalyze": True},
                headers=auth,
            )
            check("reanalyze 请求成功", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
            check("reanalyze_enqueued 为 true", r.json().get("reanalyze_enqueued") is True, str(r.json()))
            row = await db_fetch_one(
                "SELECT payload->>'force_analyze' FROM tasks "
                "WHERE type = 'analyze_image' AND payload->>'image_id' = :iid "
                "ORDER BY created_at DESC LIMIT 1",
                iid=str(image_id),
            )
            check("分析任务带 force_analyze 标记", bool(row and row[0] == "true"), str(row))

            # ---------- 建议接口权限校验 ----------
            r = await client.post(
                f"/images/{image_id}/subjects/suggest",
                json={"subject_id": subject_a},
                headers=auth,
            )
            check("有编辑权限者提建议被拒(400)", r.status_code == 400, f"{r.status_code} {r.text[:150]}")

        finally:
            # ---------- 清理测试数据 ----------
            print("清理测试数据...")
            # 等待强制分析任务失败退出（测试图片无实际文件），避免删除时任务仍在处理
            await asyncio.sleep(8)
            if image_id is not None:
                await db_exec(
                    "DELETE FROM tasks WHERE payload->>'image_id' = :iid", iid=str(image_id)
                )
                await db_exec("DELETE FROM images WHERE id = :iid", iid=image_id)
            if subject_ids:
                await db_exec(
                    "DELETE FROM subject_samples WHERE subject_id = ANY(:sids)", sids=subject_ids
                )
                await db_exec("DELETE FROM subjects WHERE id = ANY(:sids)", sids=subject_ids)
            for tid in tag_ids:
                await db_exec("DELETE FROM tags WHERE id = :tid", tid=tid)
            print("清理完成")

    print(f"\n结果: {len(PASSED)} 通过, {len(FAILED)} 失败")
    if FAILED:
        for name in FAILED:
            print(f"  失败项: {name}")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010/api/v1")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.base)))
