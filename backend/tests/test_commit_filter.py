"""GET /api/runs 的代码提交哈希过滤测试（服务端过滤，SQLite 内存库）。"""

import hashlib
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token
from app.cqrs import complete_run, start_run
from app.database import Base, get_db
from app.main import app


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# 与 backend/seed.py 一致的三个提交哈希
COMMIT_A = "a1b2c3d4e5f6789012345678abcdef0123456789"  # protein-folding / completed
COMMIT_B = "f0e1d2c3b4a5968778695a4b3c2d1e0f98765432"  # drug-screen / completed
COMMIT_C = "9abc8def7a6543210fedcba9876543210abcdef0"  # protein-folding / running

RESEARCHER_HEADERS = {
    "Authorization": f"Bearer {create_access_token('researcher', 'researcher')}"
}
AUDITOR_HEADERS = {"Authorization": f"Bearer {create_access_token('auditor', 'auditor')}"}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # JSONB not available on SQLite — remap via create_all with JSON
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(_type, compiler, **kw):
        return "JSON"

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db

    # 与 seed.py 同构的三条 Run：2 条已完成 + 1 条进行中
    # 注意：SQLite 下 UUID 列为 NUMERIC 亲和性，全数字 hex 会被转成浮点，
    # 因此测试使用含字母的固定 UUID（生产 Postgres 为原生 UUID，无此问题）
    run1 = start_run(
        session,
        actor="researcher",
        project="protein-folding",
        name="AlphaFold baseline v1",
        dataset_content_sha256=sha("casp14-subset-v1"),
        code_commit_sha=COMMIT_A,
        description=None,
        run_id=UUID("aaaaaaa1-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    complete_run(
        session,
        run_id=run1.id,
        actor="researcher",
        result_summary="done",
        expected_version=run1.version,
    )
    run2 = start_run(
        session,
        actor="researcher",
        project="drug-screen",
        name="Kinase panel screen #42",
        dataset_content_sha256=sha("kinase-panel-2024q3"),
        code_commit_sha=COMMIT_B,
        description=None,
        run_id=UUID("bbbbbbb2-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    complete_run(
        session,
        run_id=run2.id,
        actor="researcher",
        result_summary="done",
        expected_version=run2.version,
    )
    start_run(
        session,
        actor="researcher",
        project="protein-folding",
        name="Fine-tune with MSA augmentation",
        dataset_content_sha256=sha("casp14-msa-aug-v2"),
        code_commit_sha=COMMIT_C,
        description=None,
        run_id=UUID("ccccccc3-cccc-cccc-cccc-cccccccccccc"),
    )

    # 不使用 with 语句，避免触发 lifespan 去连 Postgres
    yield TestClient(app)

    app.dependency_overrides.clear()
    session.close()


def get_runs(client, headers=RESEARCHER_HEADERS, **params):
    resp = client.get("/api/runs", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_prefix_match_returns_only_matching(client):
    # 种子哈希前几位走前缀：只剩匹配项
    runs = get_runs(client, commit="a1b2", commit_match="prefix")
    assert len(runs) == 1
    assert runs[0]["code_commit_sha"] == COMMIT_A

    runs = get_runs(client, commit="9abc8def", commit_match="prefix")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_C]


def test_exact_match_requires_full_hash(client):
    # 同样的前几位改精确模式：无命中，返回空列表而非全表
    runs = get_runs(client, commit="a1b2", commit_match="exact")
    assert runs == []

    runs = get_runs(client, commit=COMMIT_A, commit_match="exact")
    assert len(runs) == 1
    assert runs[0]["code_commit_sha"] == COMMIT_A


def test_match_is_case_insensitive(client):
    # 大小写规则：不区分大小写，输入统一按小写十六进制比对
    runs = get_runs(client, commit="A1B2C3D4", commit_match="prefix")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_A]

    runs = get_runs(client, commit=COMMIT_A.upper(), commit_match="exact")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_A]


def test_default_match_mode_is_exact(client):
    runs = get_runs(client, commit=COMMIT_B)
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_B]

    runs = get_runs(client, commit="f0e1d2c3")
    assert runs == []


def test_combines_with_project_and_status(client):
    runs = get_runs(client, commit="9abc", commit_match="prefix", project="protein-folding")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_C]

    # 哈希命中但状态不命中 → 空列表
    runs = get_runs(client, commit="9abc", commit_match="prefix", status="completed")
    assert runs == []

    runs = get_runs(client, commit="9abc", commit_match="prefix", status="running")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_C]

    # 哈希命中但项目不命中 → 空列表
    runs = get_runs(client, commit="9abc", commit_match="prefix", project="drug-screen")
    assert runs == []


def test_no_match_returns_empty_list(client):
    runs = get_runs(client, commit="deadbeef", commit_match="prefix")
    assert runs == []

    runs = get_runs(client, commit="0" * 40, commit_match="exact")
    assert runs == []


def test_invalid_commit_rejected(client):
    resp = client.get(
        "/api/runs",
        params={"commit": "not-hex!"},
        headers=RESEARCHER_HEADERS,
    )
    assert resp.status_code == 400

    resp = client.get(
        "/api/runs",
        params={"commit": "a" * 65},
        headers=RESEARCHER_HEADERS,
    )
    assert resp.status_code == 400


def test_invalid_match_mode_rejected(client):
    resp = client.get(
        "/api/runs",
        params={"commit": "a1b2", "commit_match": "fuzzy"},
        headers=RESEARCHER_HEADERS,
    )
    assert resp.status_code == 400


def test_auditor_can_filter_by_commit(client):
    runs = get_runs(client, headers=AUDITOR_HEADERS, commit="f0e1", commit_match="prefix")
    assert [r["code_commit_sha"] for r in runs] == [COMMIT_B]

    runs = get_runs(client, headers=AUDITOR_HEADERS, commit="f0e1", commit_match="exact")
    assert runs == []


def test_unauthenticated_rejected(client):
    resp = client.get("/api/runs", params={"commit": "a1b2"})
    assert resp.status_code == 401
