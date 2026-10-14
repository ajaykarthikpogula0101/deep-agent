"""Network classification and company matching (app/network.py): pure, no network calls."""
from __future__ import annotations

import re

import pytest

from app import network
from app.network import classify, clean_org, domain_root, label, match, org_key, registrable, same_company, tz_mismatch

IP_LIKE = re.compile(r"\d{1,3}[-.]\d{1,3}[-.]\d{1,3}")


def ok(**kw):
    return {"status": "ok", "flags": {"mobile": None, "proxy": None, "hosting": None}, **kw}


CASES = [
    ({"status": "private"}, "local", None),
    (ok(flags={"proxy": True, "mobile": False, "hosting": False}, as_org="Some ISP"), "privacy", False),
    (ok(flags={"proxy": False, "mobile": False, "hosting": True}, as_org="Example"), "hosting", False),
    (ok(type="business", as_org="Example"), "corporate", None),
    (ok(type="isp", as_org="Example"), "consumer", None),
    (ok(asn=55836, as_org="Reliance Jio Infocomm Limited"), "consumer", None),
    (ok(asn=45609, as_org="Bharti Airtel Ltd. AS for GPRS Service"), "consumer", True),
    (ok(asn=24309, as_org="Atria Convergence Technologies Pvt. Ltd."), "consumer", None),
    (ok(asn=16509, as_org="Amazon.com, Inc."), "hosting", None),
    (ok(asn=53813, as_org="ZSCALER, INC."), "privacy", None),
    (ok(asn=36183, as_org="Akamai Technologies, Inc."), "privacy", None),
    (ok(as_org="Indian Institute of Technology Madras"), "education", None),
    (ok(as_org="National Informatics Centre", net_domain="nic.in"), "government", None),
    (ok(as_org="WeWork"), "coworking", None),
    (ok(asn=4755, as_org="TATA Communications", org="Infosys Limited", org_scope="netblock",
        flags={"mobile": False, "proxy": False, "hosting": False}), "corporate", False),
    (ok(asn=24560, as_org="Bharti Airtel Ltd. Telemedia Services", org=None, org_scope="asn", isp="Bharti Airtel"), "consumer", None),
    (ok(as_org="Palo Alto Networks, Inc.", isp="Palo Alto Networks, Inc."), "unknown", None),
    (ok(as_org="Apple Inc.", isp="Apple Inc."), "unknown", None),
]


@pytest.mark.parametrize("geo,kind,mobile", CASES)
def test_classify_table(geo, kind, mobile):
    k, why, m = classify(geo)
    assert (k, m) == (kind, mobile), why
    assert why and not IP_LIKE.search(why)


def test_classify_why_never_carries_an_ip_or_hostname():
    geo = ok(asn=24560, as_org="Bharti Airtel", rdns_domain="airtelbroadband.in", rdns_dynamic=True)
    for g in [geo] + [c[0] for c in CASES]:
        assert not IP_LIKE.search(classify(g)[1])
    # a static reverse-DNS name on its own domain points at a company
    k, why, _ = classify(ok(as_org="Small Regional Carrier", net_domain="carrier.example", rdns_domain="acme.co.in",
                            rdns_dynamic=False))
    assert k == "corporate" and "acme.co.in" in why
    assert classify(ok(as_org="Small Regional Carrier", rdns_domain="carrier.example", rdns_dynamic=True))[0] == "unknown"


@pytest.mark.parametrize("as_org,rd,kind", [
    ("Small Regional Carrier", "smallregionalcarrier.net", "unknown"),   # the carrier's own name
    ("Rural Digital Link", "rdlnet.in", "unknown"),                      # its initials
    ("Smallcarrier Networks", "smallcarrier.example", "unknown"),
    ("Small Regional Carrier", "acme.co.in", "corporate"),               # someone else's domain still counts
])
def test_rdns_rule_without_a_provider_domain(as_org, rd, kind):
    """GeoLite2 (mmdb) gives no net_domain: a static PTR on the carrier's own domain must not read as a company network."""
    assert classify(ok(asn=64500, as_org=as_org, rdns_domain=rd, rdns_dynamic=False))[0] == kind


def test_names_and_domains():
    assert org_key("Apple.INC") == "apple"
    assert org_key("Infosys Limited") == "infosys"
    assert org_key("Tech Mahindra Ltd") == "tech mahindra"
    assert org_key("Tata Consultancy Services Limited") == "tata consultancy services"
    assert same_company("tata consultancy", "tata consultancy services") is True
    assert same_company("mahindra", "tech mahindra") is False
    assert same_company("apple", "applied materials") is False
    assert same_company("global logic", "globallogic") is True
    assert same_company("", "apple") is False and same_company("apple", "") is False
    assert registrable("mail.infosys.co.in") == "infosys.co.in" and domain_root("mail.infosys.co.in") == "infosys"
    assert registrable("www.google.com") == "google.com" and domain_root("") == ""
    assert clean_org("Atria Convergence Technologies Pvt. Ltd.") == "Atria Convergence Technologies"
    assert clean_org("TATA COMMUNICATIONS") == "Tata Communications" and clean_org("ACT") == "ACT"
    assert clean_org("Apple Inc.") == "Apple"


def test_match():
    apple = {"kind": "unknown", "as_org": "Apple Inc.", "net_domain": "apple.com"}
    assert match(apple, "Apple.INC", "gmail.com", "personal")["match"] == "claim"
    jio = {"kind": "consumer", "as_org": "Reliance Jio Infocomm Limited", "net_domain": "jio.com"}
    assert match(jio, "Reliance", "gmail.com", "personal")["match"] == "consumer"
    azure = {"kind": "hosting", "as_org": "Microsoft Corporation", "asn": 8075, "net_domain": "microsoft.com"}
    assert match(azure, "Microsoft", "gmail.com", "personal")["match"] == "hosting"
    infosys = {"kind": "corporate", "net_org": "Infosys Limited"}
    assert match(infosys, "", "infosys.com", "business")["match"] == "email"
    google = {"kind": "hosting", "as_org": "Google LLC", "asn": 15169, "net_domain": "google.com"}
    assert match(google, "", "google.com", "business")["match"] == "email"
    aws = {"kind": "hosting", "as_org": "Amazon.com, Inc.", "asn": 16509, "net_domain": "amazon.com"}
    assert match(aws, "", "acme.com", "business")["match"] == "hosting"
    m = match(infosys, "Apple.INC", "gmail.com", "personal")
    assert m["match"] == "mismatch" and "Apple.INC" in m["text"] and "Infosys" in m["text"]
    assert match(infosys, "", "gmail.com", "personal")["match"] == "other_company"
    assert match({"kind": "local"}, "Apple.INC", "gmail.com", "personal")["match"] == "local"


def test_labels_and_timezones():
    assert label("consumer", True) == "mobile network" and label("consumer", None) == "home broadband"
    assert label("privacy") == "VPN, relay or security proxy" and label("local") == "local test network"
    assert label(None) == "network type unknown" and label("corporate") == "company network"
    assert tz_mismatch("Asia/Calcutta", "Asia/Kolkata") is False
    assert tz_mismatch("Asia/Kolkata", "America/New_York") is True
    assert tz_mismatch("Asia/Kolkata", "Asia/Dubai") is False
    assert tz_mismatch(None, "Asia/Kolkata") is False and tz_mismatch("Not/AZone", "Asia/Kolkata") is False
    assert set(network.KNOWN_ASN) and 4755 not in network.KNOWN_ASN and 701 not in network.KNOWN_ASN
