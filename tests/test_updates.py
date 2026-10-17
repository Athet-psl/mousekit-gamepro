import unittest

from mousekit import models, updates, usbinfo

# The GM500W's second interface: keyboard, consumer keys and the two vendor collections.
GM500W_KEYS = bytes.fromhex(
    "05010906a1018503050719e029e71500250195087501810295067508150026ff000507190029e78100c0050c0901a101"
    "850219002a9c021500269c02950175108100c00600ff0901a1018506150026ff00092f950275088102c00601ff0901a1"
    "018507150026ff00092095077508b102c005010980a1018508198129831500250175019503810295058101c0")


def release(tag, body="", assets=(), **extra):
    return {"tag_name": tag, "body": body, "published_at": "2026-10-17T10:00:00Z",
            "assets": [{"name": name, "browser_download_url": f"https://example/{name}", **meta}
                       for name, meta in assets], **extra}


class UpdatesTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v0.2.17"), (0, 2, 17))
        self.assertEqual(updates.parse_version("0.2"), (0, 2))
        self.assertIsNone(updates.parse_version("nightly"))

    def test_newer_and_recent(self):
        releases = [release("v0.2.9"), release("v0.2.10"), release("v0.2.8"),
                    release("v0.2.11", draft=True), release("v0.2.12", prerelease=True), release("latest")]
        self.assertEqual([r["tag_name"] for r in updates.newer_releases(releases, "0.2.8")], ["v0.2.10", "v0.2.9"])
        self.assertEqual([r["tag_name"] for r in updates.recent_releases(releases, "0.2.9")], ["v0.2.9", "v0.2.8"])
        self.assertEqual(updates.newer_releases(releases, "0.2.10"), [])

    def test_deb_asset(self):
        r = release("v0.2.9", assets=[("notes.txt", {}), ("mousekit_0.2.9_all.deb", {"digest": "sha256:ab12"})])
        self.assertEqual(updates.deb_asset(r), ("mousekit_0.2.9_all.deb", "https://example/mousekit_0.2.9_all.deb", "ab12"))
        self.assertIsNone(updates.deb_asset(release("v0.2.9")))

    def test_changelog(self):
        text = updates.changelog([release("v0.2.10", "**Fix DPI**"), release("v0.2.9", "**Add lighting**")])
        self.assertTrue(text.startswith("### 0.2.10  ·  2026-10-17\n\n**Fix DPI**"))
        self.assertIn("### 0.2.9", text)

    def test_new_mouse_issue(self):
        url = updates.new_mouse_issue("GamePro GM300", "30fa:1441", "dump text")
        self.assertIn("template=new-mouse.yml", url)
        self.assertIn("usb-id=30fa%3A1441", url)
        self.assertIn("dump=dump+text", url)


class ModelsTest(unittest.TestCase):
    def test_identify(self):
        self.assertEqual(models.identify("30fa:1440")["name"], "GamePro GM500W")
        self.assertIsNone(models.identify("046d:c077"))
        self.assertEqual(models.display_name("046d:c077", "USB Optical Mouse"), "USB Optical Mouse")


class DescriptorTest(unittest.TestCase):
    def test_gm500w_vendor_interface(self):
        lines = usbinfo.describe_report_descriptor(GM500W_KEYS)
        text = "\n".join(lines)
        self.assertIn("collection: page 0xff01 / 0x01 (vendor)", text)
        self.assertIn("report 7: feature 7 bytes", text)
        self.assertIn("report 2: input 2 bytes", text)


if __name__ == "__main__":
    unittest.main()
