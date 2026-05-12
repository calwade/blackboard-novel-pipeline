"""Genre Extractor — extract genre packs from source novels.

Two entry points (decoupled by output location):
  - to_project:  produce era.md etc for a specific book (projects/<book-id>/)
  - to_preset:   produce a reusable genre preset (presets/<preset-id>/)

See docs/superpowers/specs/book-centric-workflow-design.md for the full design.
"""
