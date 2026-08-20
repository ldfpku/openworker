# zh-CN.json

Flat map of `{ "<English source string>": "<Chinese translation>" }`. The English string
rendered in the component IS the key — copy it verbatim (including any `{{placeholder}}`
interpolation) rather than inventing a shorter id. A key with no entry here falls back to
itself, i.e. renders in English, so this file only ever needs to grow by addition.

A house glossary enforcing one Chinese rendering per recurring term (conversation, connector,
provider, workspace, etc.) is coming in a later pass — until then, keep translations short,
use full-width punctuation, and leave proper nouns (OpenWorker, Slack, Gmail, API key, token,
Tauri, MCP) in English.
