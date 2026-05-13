"""Genre assets tooling — create genre presets from various sources.

Entry points (v2 architecture):
  - miners.novel_dna: 从 N 本素材小说融合创造新 preset（同框架换核心设定）
  - miners.sensory_kit: 从作品已产章节抽 location→5感清单给 Planner 用
  - blank_preset: 手动建空壳 preset
  - from_description: 从一段自由描述让 LLM 造 preset（单次调用，轻量）

旧版（extractor→merger→drafter→validator 四段式 pipeline）已于 2026-05-14
删除。历史详见 docs/superpowers/specs/genre-mining-v2-step1-sensory-kit.md
和 git log commit fb8bbf7（NovelDNA 上线）。
"""
