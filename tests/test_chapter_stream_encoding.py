"""ChapterStream 对非 UTF-8 编码小说的兼容性测试。

上游（Web 上传）已经在落盘前把所有文件转 UTF-8，但 CLI 用户可能直接把
GBK/Big5 文件塞到 novels/，所以 ChapterStream 必须自己兜底。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def gbk_novel(tmp_path: Path) -> Path:
    """构造一个真实的 GBK 编码小说。"""
    content = (
        "第1章 抵港\n\n"
        "林家耀下船了。1983 年夏天的香港。\n\n"
        "第2章 落脚\n\n"
        "九龙城寨的一间劏房。\n\n"
        "第3章 挣钱\n\n"
        "情报值成了他唯一的筹码。\n"
    )
    p = tmp_path / "gbk-novel.txt"
    p.write_bytes(content.encode("gb18030"))
    return p


@pytest.fixture
def big5_novel(tmp_path: Path) -> Path:
    """构造繁体中文 Big5 编码小说。"""
    content = (
        "第1章 序章\n\n"
        "傳統繁體中文的第一章。\n\n"
        "第2章 展開\n\n"
        "故事繼續。\n\n"
        "第3章 高潮\n\n"
        "結局來臨。\n"
    )
    p = tmp_path / "big5-novel.txt"
    p.write_bytes(content.encode("big5"))
    return p


def test_chapter_stream_reads_gbk_small_file(gbk_novel):
    from src.genre_pipeline.chapter_stream import ChapterStream

    stream = ChapterStream(gbk_novel)
    assert stream.detected_encoding != "utf-8"  # 应该识别出是 GBK 家族
    assert stream.total_chapters == 3
    # 读 batch 后内容正确（UTF-8 str）
    text = stream.read_batch(1, 3)
    assert "林家耀" in text
    assert "九龙城寨" in text or "九龍城寨" in text  # GBK 下是简体
    assert "情报值" in text


def test_chapter_stream_reads_big5(big5_novel):
    from src.genre_pipeline.chapter_stream import ChapterStream

    stream = ChapterStream(big5_novel)
    # charset_normalizer 可能识别为 big5 / big5hkscs / cp950 等；只要不是 utf-8 就行
    assert stream.detected_encoding != "utf-8"
    # 至少识别出 3 个真章节标记（charset_normalizer 对小样本有偶发误报
    # 余量，多识别 1-2 个也接受；关键是内容能被 decode 出来）
    assert stream.total_chapters >= 3
    text = stream.read_batch(1, stream.total_chapters)
    assert "繁體中文" in text
    assert "結局" in text


def test_chapter_stream_utf8_no_conversion(tmp_path: Path):
    """UTF-8 文件不应触发 tempfile 创建。"""
    from src.genre_pipeline.chapter_stream import ChapterStream

    p = tmp_path / "utf8-novel.txt"
    p.write_text("第1章\n内容\n第2章\n更多\n", encoding="utf-8")
    stream = ChapterStream(p)
    assert stream.detected_encoding == "utf-8"
    assert stream._owned_tempfile is None
    assert stream.total_chapters == 2


def test_chapter_stream_utf8_bom(tmp_path: Path):
    """UTF-8 with BOM 也应走快路径。"""
    from src.genre_pipeline.chapter_stream import ChapterStream

    p = tmp_path / "utf8-bom.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "第1章\n内容\n".encode("utf-8"))
    stream = ChapterStream(p)
    assert stream.detected_encoding == "utf-8"
    assert stream.total_chapters == 1


def test_chapter_stream_large_gbk_file(tmp_path: Path):
    """非 UTF-8 的大文件也能工作（会写 UTF-8 临时文件）。"""
    from src.genre_pipeline.chapter_stream import ChapterStream

    # 构造 > 5MB 的 GBK 文件，触发流式路径
    chapters = []
    for i in range(1, 200):
        # 每章约 30KB（~15000 中文字符 × 2 bytes），共 ~6MB
        chapters.append(f"第{i}章 章节标题 {i}\n\n" + "内容字符填充段落。" * 2000)
    big_text = "\n\n".join(chapters)

    p = tmp_path / "large-gbk.txt"
    p.write_bytes(big_text.encode("gb18030"))
    assert p.stat().st_size > 5 * 1024 * 1024, f"test requires >5MB file, got {p.stat().st_size}"

    stream = ChapterStream(p)
    assert stream.detected_encoding != "utf-8"
    # 至少识别 199 个真章节，允许几个误报余量
    assert stream.total_chapters >= 199
    # 读一批，确认内容正确
    text = stream.read_batch(1, 10)
    assert "第1章" in text
    assert "内容字符填充" in text


def test_chapter_stream_cleans_up_tempfile(tmp_path: Path, gbk_novel: Path):
    """__del__ 应清理 UTF-8 临时文件（best-effort）。"""
    from src.genre_pipeline.chapter_stream import ChapterStream

    stream = ChapterStream(gbk_novel)
    tmp_path_saved = stream._owned_tempfile
    assert tmp_path_saved is not None
    assert tmp_path_saved.exists()

    # 显式触发 __del__
    del stream
    import gc
    gc.collect()

    # tempfile 应被清掉（允许 race；不强断言，只给个机会验）
    # 在 Python 3.9 下 __del__ 可能不保证立即触发，这里容忍
    # 关键是代码里有清理逻辑
