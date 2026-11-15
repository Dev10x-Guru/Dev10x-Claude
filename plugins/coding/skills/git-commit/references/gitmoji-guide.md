# Gitmoji Guide

Complete reference for gitmoji usage in commit messages.

## Common Gitmojis

| Gitmoji | Code | When to Use |
|---------|------|-------------|
| ✅ | `:white_check_mark:` | Adding, updating, or fixing tests |
| 🐛 | `:bug:` | Fixing a bug |
| ♻️ | `:recycle:` | Refactoring code |
| ✨ | `:sparkles:` | Introducing new features |
| 📝 | `:memo:` | Adding or updating documentation |
| 🔒 | `:lock:` | Fixing security issues |
| ⚡ | `:zap:` | Improving performance |
| 💄 | `:lipstick:` | Adding or updating UI and style files |
| 🔧 | `:wrench:` | Adding or updating configuration files |
| 🚀 | `:rocket:` | Deploying stuff |
| 🔥 | `:fire:` | Removing code or files |
| 🚨 | `:rotating_light:` | Fixing compiler/linter warnings |
| 🎨 | `:art:` | Improving structure/format of code |
| 🔖 | `:bookmark:` | Releasing/version tags |

## Usage Guidelines

### Test Changes
Use ✅ for:
- Adding new tests
- Fixing flaky tests
- Updating test assertions
- Improving test coverage

**Examples:**
- `✅ PAY-310 Fix flaky tests with non-zero tax amounts`
- `✅ PAY-201 Add tests for discount validation`

### Bug Fixes
Use 🐛 for:
- Fixing production bugs
- Correcting incorrect behavior
- Resolving errors

**Examples:**
- `🐛 PAY-133 Fix motor timeout in payment processing`
- `🐛 PAY-275 Fix tax calculation for exempt customers`

### Refactoring
Use ♻️ for:
- Code restructuring
- Extracting methods/classes
- Removing duplication
- Improving code quality without changing behavior

**Examples:**
- `♻️ PAY-200 Refactor payment repository to use base class`
- `♻️ PAY-180 Extract discount validation to service`

### New Features
Use ✨ for:
- Adding new functionality
- Implementing new business features
- New user-facing capabilities

**Examples:**
- `✨ PAY-220 Add discount code system`
- `✨ PAY-195 Add customer loyalty points`

### Documentation
Use 📝 for:
- README updates
- Code comments
- API documentation
- Architecture diagrams

**Examples:**
- `📝 Update README with new setup instructions`
- `📝 Add ADR for payment retry strategy`

### Security
Use 🔒 for:
- Security vulnerability fixes
- Authentication improvements
- Authorization changes
- Sensitive data protection

**Examples:**
- `🔒 PAY-240 Fix SQL injection in search`
- `🔒 PAY-189 Add rate limiting to API`

### Performance
Use ⚡ for:
- Speed optimizations
- Query improvements
- Caching implementations
- Reducing memory usage

**Examples:**
- `⚡ PAY-211 Optimize search query with indexes`
- `⚡ PAY-156 Cache tax settings lookup`

### UI/Styling
Use 💄 for:
- CSS changes
- UI component updates
- Visual improvements
- Accessibility improvements

**Examples:**
- `💄 PAY-203 Update checkout button styling`
- `💄 PAY-178 Improve mobile responsiveness`

### Configuration
Use 🔧 for:
- Config file changes
- Environment variables
- Build configuration
- CI/CD updates

**Examples:**
- `🔧 Update Docker compose for new service`
- `🔧 Add production environment variables`

## Multiple Changes?

If a commit includes multiple types of changes, use the **primary** gitmoji:

**Example:** Adding a feature that also includes tests
- Primary: Feature (✨)
- Secondary: Tests (mentioned in solution)
- Use: `✨ PAY-220 Add discount validation` (mention tests in body)

**Example:** Refactoring that fixes a bug
- If bug fix is primary: `🐛 PAY-150 Fix and refactor payment calc`
- If refactoring is primary: `♻️ PAY-150 Refactor payment calc fixing bug`

## Choosing the Right Gitmoji

Ask yourself:
1. **What's the primary purpose?** (feature/fix/refactor/test)
2. **What would a reviewer focus on?** (the main change)
3. **What's in the title?** (should match the gitmoji)

**Priority order when multiple changes:**
1. 🔒 Security (always highest priority)
2. 🐛 Bug fixes
3. ✨ New features
4. ♻️ Refactoring
5. ✅ Tests
6. 📝 Documentation

## Format in Commits

Use the **emoji character**, not the code:

✅ Correct:
```
✅ PAY-310 Fix flaky tests
```

❌ Incorrect:
```
:white_check_mark: PAY-310 Fix flaky tests
```

The emoji character renders properly in:
- GitHub
- GitLab
- Terminal (with proper font)
- IDEs

## Additional Gitmojis (Less Common)

| Gitmoji | Code | When to Use |
|---------|------|-------------|
| 🚀 | `:rocket:` | Deploying |
| 🔥 | `:fire:` | Removing code/files |
| 🚨 | `:rotating_light:` | Fixing linter warnings |
| 🎨 | `:art:` | Improving structure |
| 🔖 | `:bookmark:` | Version tags |
| 🚧 | `:construction:` | Work in progress |
| ⬆️ | `:arrow_up:` | Upgrading dependencies |
| ⬇️ | `:arrow_down:` | Downgrading dependencies |
| 📦 | `:package:` | Updating dependencies |
| 🔀 | `:twisted_rightwards_arrows:` | Merging branches |

Use these sparingly and only when they're the clear primary action.
