import importlib.util
from pathlib import Path
import pytest
p=Path(__file__).resolve().parents[1]/'collection_evidence.py';s=importlib.util.spec_from_file_location('collection_helper',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
@pytest.mark.parametrize('u',['http://nsearchives.nseindia.com/corporate/a.xml','https://evil.example/corporate/a.xml','https://nsearchives.nseindia.com.evil.example/corporate/a.xml','https://user:password@nsearchives.nseindia.com/corporate/a.xml','https://nsearchives.nseindia.com:444/corporate/a.xml','https://nsearchives.nseindia.com/api/other','https://finance.yahoo.com/a'])
def test_non_official_requests_refused(u):assert not m.allowed(u)
@pytest.mark.parametrize('p',['corporate/xbrl/a.xml','content/cm/a.zip','content/indices/a.csv','content/circulars/a.pdf'])
def test_named_official_resources_allowed(p):assert m.allowed('https://nsearchives.nseindia.com/'+p)
def test_redirects_refused():
 with pytest.raises(ValueError):m.NoRedirect().redirect_request(None,None,None,None,None,None)
