"""赛道常量。

被配置层（校验关键词组）与分析层（分类）共用，所以放在顶层、不依赖任何模块。
"""

from __future__ import annotations

from typing import Literal

AI = "AI"
WEB3 = "Web3"
SEC = "安全"
BACKEND = "后端"
OTHER = "其他"

#: 可配置、可统计的四条赛道（不含兜底的「其他」）
TRACKS: tuple[str, ...] = (AI, WEB3, SEC, BACKEND)
#: 含兜底项的全集
ALL_TRACKS: tuple[str, ...] = (*TRACKS, OTHER)

TrackName = Literal["AI", "Web3", "安全", "后端"]

Track = str

__all__ = ["AI", "ALL_TRACKS", "BACKEND", "OTHER", "SEC", "TRACKS", "WEB3", "Track", "TrackName"]
