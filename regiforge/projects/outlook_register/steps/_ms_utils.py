"""Outlook 注册共享工具：随机账号资料 + 人性化鼠标/键盘操作。

迁移自外部仓库 `OutlookRegister/utils.py` + `controllers/base_controller.py`，
按 RegiForge 异步 Playwright 规范改写，并去掉 faker 外部依赖（内嵌姓名表）。
仅服务本项目流程，不新建 Provider。
"""
from __future__ import annotations

import random
import secrets
import string
from typing import Any

# 英文姓名表（替代外部仓库的 faker 依赖，足够随机）
_FIRST_NAMES = (
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph",
    "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Lisa",
    "Daniel", "Nancy", "Matthew", "Betty", "Anthony", "Margaret", "Mark",
    "Sandra", "Donald", "Ashley", "Steven", "Kimberly", "Paul", "Emily",
    "Andrew", "Donna", "Joshua", "Michelle", "Kenneth", "Carol", "Kevin",
    "Amanda", "Brian", "Dorothy", "George", "Melissa", "Timothy", "Deborah",
    "Ronald", "Stephanie", "Edward", "Rebecca", "Jason", "Sharon", "Jeffrey",
    "Laura", "Ryan", "Cynthia", "Jacob", "Amy", "Gary", "Angela",
)
_LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes",
)


def random_email_alias(length: int | None = None) -> str:
    """生成 Outlook 邮箱前缀（小写字母 + 少量数字，首字符必须字母）。"""
    if length is None:
        length = random.randint(12, 14)
    first_char = random.choice(string.ascii_lowercase)
    other = []
    for _ in range(length - 1):
        if random.random() < 0.07:
            other.append(random.choice(string.digits))
        else:
            other.append(random.choice(string.ascii_lowercase))
    return first_char + "".join(other)


def generate_strong_password(length: int | None = None) -> str:
    """生成包含大小写/数字/符号的强密码（微软要求至少 8 位含三类）。"""
    if length is None:
        length = random.randint(11, 15)
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = "".join(secrets.choice(chars) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)
        ):
            return password


def random_person() -> dict[str, str]:
    """随机姓名 + 生日（1960–2005）。"""
    return {
        "lastname": random.choice(_LAST_NAMES),
        "firstname": random.choice(_FIRST_NAMES),
        "year": str(random.randint(1960, 2005)),
        "month": str(random.randint(1, 12)),
        "day": str(random.randint(1, 28)),
    }


class Humanizer:
    """模拟真人鼠标轨迹与输入节奏（异步 Playwright 版）。

    移植自外部仓库 base_controller 的 smooth_move_to / smooth_click /
    smooth_type / wait_random_ratio。
    """

    def __init__(self, page: Any, bot_protection_wait: float = 16.0) -> None:
        self.page = page
        self.wait_time = max(1.0, float(bot_protection_wait)) * 1000  # ms
        self._last_pos: tuple[float, float] | None = None

    async def wait_ratio(self, ratio: float, delta: float = 0.02) -> None:
        """按 bot_protection_wait 的比例等待，模拟人类阅读/输入间隔。"""
        actual = random.uniform(ratio, ratio + delta)
        await self.page.wait_for_timeout(int(actual * self.wait_time))

    def _rand_rest(self) -> int:
        return random.randint(60, 160)

    async def smooth_move_to(self, tx: float, ty: float, steps: int | None = None) -> None:
        """从上一次鼠标位置平滑移动到目标。"""
        lx, ly = self._last_pos or (random.uniform(150, 450), random.uniform(100, 350))
        if self._last_pos is None:
            try:
                await self.page.mouse.move(lx, ly)
            except Exception:
                pass
        if steps is None:
            steps = random.randint(6, 14)
        try:
            await self.page.mouse.move(tx, ty, steps=steps)
        except Exception:
            pass
        self._last_pos = (float(tx), float(ty))

    async def smooth_click(self, locator: Any, offset_range: int = 5) -> bool:
        """带偏移的鼠标点击；locator.bounding_box 失败时回退 locator.click()。"""
        try:
            box = await locator.bounding_box()
            if not box:
                await locator.click(timeout=5000)
                return False
            tx = box["x"] + box["width"] / 2 + random.uniform(-offset_range, offset_range)
            ty = box["y"] + box["height"] / 2 + random.uniform(-offset_range, offset_range)
            await self.smooth_move_to(tx, ty)
            await self.page.wait_for_timeout(self._rand_rest())
            await self.page.mouse.click(tx, ty)
            self._last_pos = (float(tx), float(ty))
            return True
        except Exception:
            try:
                await locator.click(timeout=5000)
            except Exception:
                pass
            return False

    async def smooth_type(self, locator: Any, text: str, click_first: bool = True) -> None:
        """逐字符输入，模拟真实键盘节奏。"""
        if click_first:
            await self.smooth_click(locator)
        for char in text:
            try:
                await locator.press(char)
                await self.page.wait_for_timeout(random.randint(40, 110))
            except Exception:
                break

    def reset(self) -> None:
        self._last_pos = None
