"""Tests for Step 13: the per-document pipeline and the Lambda handler. AWS is faked by moto
(in memory, offline, free) and Claude by a fake extractor, so nothing here costs money."""
import importlib
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from pipeline.process import process_document
from pipeline.schemas import CapitalCall
from pipeline.validate import MasterData

MASTER = MasterData.load()
FUND, INVESTOR = "Maple Growth Fund I", "Teresaburgh Foundation"     # a real commitment in data/master


def make_pdf(path, lines):
    c = canvas.Canvas(str(path), pagesize=letter)
    for i, line in enumerate(lines):
        c.drawString(60, 720 - 20 * i, line)
    c.save()
    return path


def fake_classify(doc_type):
    return lambda text: SimpleNamespace(doc_type=doc_type, confidence=0.95, confident=True)


def fake_extract(investor=INVESTOR):
    form = CapitalCall(fund_name=FUND, investor_name=investor, call_number=1, amount=Decimal("250000.00"),
                       due_date=date(2026, 11, 15), reference="TF CAP CALL 1")
    return lambda text, doc_type: SimpleNamespace(data=form, error=None)


def test_valid_capital_call_is_accepted(tmp_path):
    pdf = make_pdf(tmp_path / "cc.pdf", ["Capital Call Notice", FUND, INVESTOR])
    record = process_document(pdf, MASTER, fake_classify("capital_call"), fake_extract())
    assert record["status"] == "accepted" and record["fund_id"] == "FND-001"
    assert record["fields"]["due_date"] == "2026-11-15" and record["fields"]["amount"] == Decimal("250000.00")


def test_scan_without_text_needs_review_and_is_never_classified(tmp_path):
    pdf = tmp_path / "scan.pdf"
    canvas.Canvas(str(pdf)).save()                                   # a blank page: no text layer
    record = process_document(pdf, MASTER, classify=lambda t: pytest.fail("must not classify"))
    assert record["status"] == "needs_review" and "OCR" in record["errors"][0]


def test_other_documents_are_filed_without_calling_the_llm(tmp_path):
    pdf = make_pdf(tmp_path / "news.pdf", ["Investor Newsletter"])
    record = process_document(pdf, MASTER, fake_classify("other"),
                              extract=lambda *a: pytest.fail("must not call the LLM"))
    assert record["status"] == "filed"


def test_unknown_investor_needs_review(tmp_path):
    pdf = make_pdf(tmp_path / "cc.pdf", ["Capital Call Notice"])
    record = process_document(pdf, MASTER, fake_classify("capital_call"), fake_extract("Northwind Capital"))
    assert record["status"] == "needs_review" and any("unknown investor" in e for e in record["errors"])


@pytest.fixture
def aws(monkeypatch):
    """A fake AWS account with the bucket and table, and a freshly imported handler that uses them."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ca-central-1")
    monkeypatch.setenv("TABLE_NAME", "itl-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="inbox", CreateBucketConfiguration={"LocationConstraint": "ca-central-1"})
        boto3.client("dynamodb").create_table(
            TableName="itl-test", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}])
        import cloud.handler
        handler = importlib.reload(cloud.handler)                    # create its clients inside the mock
        yield SimpleNamespace(s3=s3, handler=handler, table=boto3.resource("dynamodb").Table("itl-test"))


def sqs_event(*keys):
    """What SQS hands Lambda: each message body is the S3 notification for one upload."""
    return {"Records": [{"messageId": f"m{i}", "body": json.dumps(
        {"Records": [{"s3": {"bucket": {"name": "inbox"}, "object": {"key": key}}}]})} for i, key in enumerate(keys)]}


def test_upload_is_processed_and_saved(aws, tmp_path):
    aws.s3.upload_file(str(make_pdf(tmp_path / "a.pdf", ["Capital Call"])), "inbox", "incoming/a.pdf")
    calls = []
    process = lambda path, master: calls.append(path) or {"status": "accepted", "doc_type": "capital_call",
                                                           "confidence": 0.91}
    result = aws.handler.handler(sqs_event("incoming/a.pdf"), None, process)
    items = aws.table.scan()["Items"]
    assert result == {"batchItemFailures": []} and len(calls) == 1
    assert items[0]["status"] == "accepted" and items[0]["s3_key"] == "incoming/a.pdf"
    assert items[0]["confidence"] == Decimal("0.91")                 # float became an exact Decimal


def test_same_file_uploaded_twice_is_processed_once(aws, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf", ["Capital Call"])
    aws.s3.upload_file(str(pdf), "inbox", "incoming/a.pdf")
    aws.s3.upload_file(str(pdf), "inbox", "incoming/a-copy.pdf")     # same bytes, different name
    calls = []
    process = lambda path, master: calls.append(path) or {"status": "accepted"}
    aws.handler.handler(sqs_event("incoming/a.pdf", "incoming/a-copy.pdf"), None, process)
    assert len(calls) == 1 and len(aws.table.scan()["Items"]) == 1


def test_s3_setup_test_event_is_ignored(aws):
    event = {"Records": [{"messageId": "t", "body": json.dumps({"Event": "s3:TestEvent"})}]}
    assert aws.handler.handler(event, None) == {"batchItemFailures": []}


def test_service_failure_is_reported_so_sqs_retries(aws, tmp_path):
    aws.s3.upload_file(str(make_pdf(tmp_path / "a.pdf", ["x"])), "inbox", "incoming/a.pdf")

    def broken(path, master):
        raise ConnectionError("API unavailable")
    result = aws.handler.handler(sqs_event("incoming/a.pdf"), None, broken)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]} and aws.table.scan()["Items"] == []