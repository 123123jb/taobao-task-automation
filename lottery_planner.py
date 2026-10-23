"""Compare a bounded set of rooms and keep a lock while waiting for a draw."""
from dataclasses import dataclass
import json
from pathlib import Path
import re


def parse_countdown(text):
    match = re.search(r'(?<!\d)(\d{1,2})\s*[:：]\s*([0-5]\d)(?!\d)', text)
    return int(match[1]) * 60 + int(match[2]) if match else None


@dataclass(frozen=True)
class Candidate:
    room: str
    index: int
    deadline: float


def choose_room(candidates, current_index, now):
    # Reserve ten seconds per room traversed and fifteen seconds to recheck/join.
    feasible = [c for c in candidates
                if c.deadline - now > abs(c.index - current_index) * 10 + 15]
    return min(feasible, key=lambda c: c.deadline, default=None)


class RoomLock:
    def __init__(self, path):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None

    def require_unlocked(self):
        if self.state is not None:
            raise RuntimeError('福袋已参与或参与结果待确认，禁止切换直播间')

    def acquire(self, room, deadline):
        self.require_unlocked()
        self.state = {'room': room, 'deadline': deadline}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)

    def release(self, result):
        if result not in ('未中奖', '本轮已结束'):
            raise ValueError('必须结束本轮等待后才能解锁')
        self.path.unlink(missing_ok=True)
        self.state = None
