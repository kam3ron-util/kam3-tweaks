import io
import json
import unittest
import urllib.error
from email.message import Message

from github_updates import fetch_latest_release, compare_release, parse_version, UpdateCheckError, RELEASES_URL


class Response:
    status=200
    def __init__(self,payload): self.data=json.dumps(payload).encode("utf-8")
    def read(self,size=-1):
        if size is None or size<0: data,self.data=self.data,b""; return data
        data,self.data=self.data[:size],self.data[size:]; return data
    def geturl(self): return "https://api.github.com/repos/kam3ron-util/kam3-tweaks/releases/latest"
    def __enter__(self): return self
    def __exit__(self,*_): return False


def payload(**changes):
    value={"id":450,"tag_name":"v4.5.0","draft":False,"prerelease":False,
           "html_url":RELEASES_URL.replace("/latest","/tag/v4.5.0"),"body":"Release notes","assets":[]}
    value.update(changes); return value


class GitHubUpdateTests(unittest.TestCase):
    def test_repository_endpoint_is_the_configured_public_repository(self):
        from github_updates import REPOSITORY, LATEST_API_URL
        self.assertEqual(REPOSITORY,"kam3ron-util/kam3-tweaks")
        self.assertEqual(LATEST_API_URL,"https://api.github.com/repos/kam3ron-util/kam3-tweaks/releases/latest")

    def test_fetches_and_validates_latest_stable_release(self):
        release=fetch_latest_release(opener=lambda request,timeout:Response(payload()))
        self.assertEqual(release["tag"],"v4.5.0")
        self.assertEqual(release["notes"],"Release notes")
        self.assertEqual(compare_release("4.3.1",release),1)
        self.assertEqual(compare_release("4.5.0",release),0)
        self.assertEqual(compare_release("4.5.1",release),-1)
        self.assertEqual(compare_release("4.6.0",release),-1)

    def test_accepts_uppercase_v_prefix_used_by_github_tag(self):
        release=fetch_latest_release(opener=lambda request,timeout:Response(payload(
            tag_name="V4.5.0",html_url=RELEASES_URL.replace("/latest","/tag/V4.5.0"))))
        self.assertEqual(release["version"],(4,5,0,0))
        self.assertEqual(compare_release("4.5.0",release),0)

    def test_three_and_four_part_versions_compare_without_trailing_zero_false_update(self):
        release=fetch_latest_release(opener=lambda request,timeout:Response(payload(
            tag_name="v4.6.1",html_url=RELEASES_URL.replace("/latest","/tag/v4.6.1"))))
        self.assertEqual(parse_version("4.6.1"),(4,6,1,0))
        self.assertEqual(parse_version("4.6.1.0"),(4,6,1,0))
        self.assertEqual(compare_release("4.6.1.0",release),0)
        self.assertEqual(compare_release("4.6.0.9",release),1)
        self.assertEqual(compare_release("4.6.2.0",release),-1)

    def test_rejects_prerelease_draft_bad_tag_and_untrusted_release_url(self):
        for change in ({"prerelease":True},{"draft":True},{"tag_name":"v4.5.0-rc1"},
                       {"html_url":"https://evil.example/release"}):
            with self.subTest(change=change), self.assertRaises(UpdateCheckError):
                fetch_latest_release(opener=lambda request,timeout,c=change:Response(payload(**c)))

    def test_handles_github_rate_limit_and_offline_errors(self):
        headers=Message(); headers["Retry-After"]="45"
        def limited(*_,**__): raise urllib.error.HTTPError("url",429,"rate",headers,io.BytesIO())
        with self.assertRaisesRegex(UpdateCheckError,"45 seconds"):
            fetch_latest_release(opener=limited)
        def offline(*_,**__): raise urllib.error.URLError("offline")
        with self.assertRaisesRegex(UpdateCheckError,"Could not reach GitHub"):
            fetch_latest_release(opener=offline)

    def test_rejects_invalid_json_and_version_formats(self):
        class Bad(Response):
            def __init__(self): self.data=b"not-json"
        with self.assertRaises(UpdateCheckError): fetch_latest_release(opener=lambda *a,**k:Bad())
        with self.assertRaises(UpdateCheckError): parse_version("latest")


if __name__=="__main__": unittest.main()
