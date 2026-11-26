import unittest

from policy import ADMIN, GUEST, MEMBER, gate, identity, matrix, parse_command

ADMINS = ["qqbot:FriendMessage:AAA"]
IDS = ["0123456789ABCDEF0123456789ABCDEF"]


class TestParseCommand(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_command("/status"), "status")
        self.assertEqual(parse_command("/Status a b"), "status")
        self.assertEqual(parse_command("/checkin@bot x"), "checkin")
        self.assertEqual(parse_command("／bind"), "bind")
        self.assertEqual(parse_command("你好"), "")
        self.assertEqual(parse_command(""), "")
        # 唤醒前缀被框架吃掉后的裸命令名
        self.assertEqual(parse_command("whoami", bare=True), "whoami")
        self.assertEqual(parse_command("你好", bare=True), "")
        self.assertEqual(parse_command("whoami", bare=False), "")

    def test_gate_bare_guest_command(self):
        self.assertTrue(gate("whoami", GUEST, bare=True)["allow"])
        self.assertFalse(gate("checkin", GUEST, bare=True)["allow"])


class TestIdentity(unittest.TestCase):
    def test_admin_by_umo(self):
        role, _ = identity(ADMINS[0], "", ADMINS, IDS)
        self.assertEqual(role, ADMIN)

    def test_admin_by_openid(self):
        role, _ = identity("other:session", IDS[0], ADMINS, IDS)
        self.assertEqual(role, ADMIN)

    def test_member(self):
        role, _ = identity("qqbot:FriendMessage:BBB", "", ADMINS, IDS,
                           ["qqbot:FriendMessage:BBB"])
        self.assertEqual(role, MEMBER)

    def test_guest(self):
        role, _ = identity("qqbot:FriendMessage:CCC", "deadbeef", ADMINS, IDS)
        self.assertEqual(role, GUEST)

    def test_open_mode_when_empty(self):
        role, reason = identity("any:where", "", [], [])
        self.assertEqual(role, ADMIN)
        self.assertIn("开放模式", reason)

    def test_member_by_openid(self):
        role, _ = identity("qqbot:FriendMessage:ZZZ", "deadbeef", ADMINS, IDS, ["deadbeef"])
        self.assertEqual(role, MEMBER)

    def test_member_allow_all(self):
        for text in ("/checkin", "/unbind x", "随便聊"):
            self.assertTrue(gate(text, MEMBER, member_allow_all=True)["allow"], text)
        self.assertFalse(gate("/checkin", MEMBER, member_allow_all=False)["allow"])

    def test_empty_umo_never_matches(self):
        role, _ = identity("", "", ADMINS, IDS, [""])
        self.assertEqual(role, GUEST)


class TestGate(unittest.TestCase):
    def test_admin_everything(self):
        for text in ("/checkin", "/unbind x", "随便聊"):
            self.assertTrue(gate(text, ADMIN)["allow"])

    def test_guest_safe_commands(self):
        for text in ("/status", "/whoami", "/checkin_bind"):
            self.assertTrue(gate(text, GUEST)["allow"], text)

    def test_guest_denied(self):
        for text in ("/login x", "/checkin", "/unbind x", "/notify_test"):
            self.assertFalse(gate(text, GUEST)["allow"], text)

    def test_guest_plain_text_denied(self):
        self.assertFalse(gate("在吗", GUEST)["allow"])

    def test_bind_switch(self):
        self.assertFalse(gate("/bind", GUEST, allow_self_bind=False)["allow"])
        self.assertTrue(gate("/bind", GUEST, allow_self_bind=True)["allow"])

    def test_member_same_as_guest(self):
        self.assertEqual(gate("/checkin", MEMBER)["allow"], gate("/checkin", GUEST)["allow"])


class TestMatrix(unittest.TestCase):
    def test_shape(self):
        data = matrix()
        self.assertEqual(len(data["rows"]), 4)
        self.assertEqual(len(data["rows"][0]["cells"]), len(data["commands"]))

    def test_admin_row_all_allowed(self):
        data = matrix()
        self.assertTrue(all(c["allow"] for c in data["rows"][0]["cells"]))

    def test_guest_row_blocks_dangerous(self):
        data = matrix()
        guest = data["rows"][-1]["cells"]
        by = {c["command"]: c["allow"] for c in guest}
        self.assertFalse(by["/checkin"])
        self.assertFalse(by["/bind"])
        self.assertTrue(by["/status"])


if __name__ == "__main__":
    unittest.main()
