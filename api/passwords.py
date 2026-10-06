"""Passwords an office can read out over the phone and still not guess.

Four words and two digits -- ``Copper-Harbour-Falcon-Marsh-47`` -- from a list of common,
unambiguous English words: about 48 bits of entropy, which for a system on the office LAN with a
login rate limit is comfortably enough, and far better than a password anybody can remember
because everybody was given the same one. Only the scrypt hash is stored (``api.auth``); the
plaintext exists once, in the credentials sheet ``api.db`` writes for the office.
"""
from __future__ import annotations

import secrets
from pathlib import Path

#: A built-in list so generation never depends on the box having a dictionary installed. Short,
#: common, easy to spell aloud; no near-homophones (no "there"/"their"), nothing offensive.
_WORDS = """
amber anchor apple arrow aspen autumn badger bamboo banner barley basin beacon birch bishop blossom
border breeze bridge bronze brook cabin camel candle canyon canvas carbon castle cedar cellar chalk
cherry cinder cipher citrus clover cobalt comet copper coral cotton crane crimson crystal cypress
dagger delta desert dolphin dragon ember falcon fennel ferry fiddle finch flint forest fossil
galaxy garden garnet gazelle ginger glacier granite gravel harbour harvest hazel heron hickory honey
horizon indigo island ivory jasmine jasper jungle juniper kestrel kettle ladder lagoon lantern larch
lemon linen locust lotus lumber magnet mango maple marble marsh meadow melon mercury mesa mint
mirror monsoon mosaic mustard nectar nickel nutmeg oasis olive onyx orbit orchid osprey otter oyster
paddle palace parrot pebble pepper pistol planet plaza plum poplar prairie quartz quiver raven
ribbon river rocket saddle saffron salmon sapphire satin scarlet shadow sierra silver sparrow
spruce summit sunset tamarind thistle thunder timber topaz tulip tundra turnip umber valley velvet
violet walnut walrus willow winter yarrow zephyr zinnia
""".split()


def generate(words: int = 4, digits: int = 2) -> str:
    picked = [secrets.choice(_WORDS).capitalize() for _ in range(words)]
    tail = "".join(str(secrets.randbelow(10)) for _ in range(digits))
    return "-".join(picked + [tail])


def write_private(path: Path, text: str, *, append: bool = False) -> None:
    """Write a file only its owner can read (the credentials sheet)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(path, mode, encoding="utf-8") as fh:
        fh.write(text)
    path.chmod(0o600)
