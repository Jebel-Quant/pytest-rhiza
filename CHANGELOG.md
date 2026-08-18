## [0.2.2] - 2026-08-18

### 💼 Other

- Add Makefile, pre-commit hooks and a CI lint job
## [0.2.1] - 2026-08-18

### ⚙️ Miscellaneous Tasks

- Add rhiza_release.yml release workflow
- Drop conda and devcontainer jobs from rhiza_release
## [0.2.0] - 2026-08-18

### 🚀 Features

- Scaffold pytest-rhiza, the rhiza checks as a plugin

### 🐛 Bug Fixes

- Do not invent bash syntax errors where bash does not work

### 🧪 Testing

- Stop assuming every platform has a working bash

### ⚙️ Miscellaneous Tasks

- Point repo at jebel-quant/rhiza@v1.3.3
- Add project skeleton + license metadata
- Run the test suite on 3.11-3.14
- Pin setup-uv to v10.0.1, not the nonexistent v10
- Test on ubuntu, macos and windows
