# Commit Message Format Guidelines

## Structure

```
<gitmoji> <ticket-ref> <short description>

<detailed explanation of the problem>

Solution:
- <solution point 1>
- <solution point 2>
- <solution point 3>

Fixes: <ticket-ref>
```

## Rules

1. **Line Length**: Title must be ≤ 72 characters
2. **Gitmoji**: Use appropriate gitmoji prefix based on commit type
3. **Ticket Reference**: Format as `PAY-XXX` (team prefix + number)
4. **Spacing**: One space after gitmoji, one space after ticket-ref
5. **Footer**: Always include `Fixes: <ticket-ref>` footer

## Common Gitmojis

- ✅ `:white_check_mark:` - Tests (adding, updating, fixing)
- 🐛 `:bug:` - Bug fixes
- ♻️ `:recycle:` - Refactoring
- ✨ `:sparkles:` - New features
- 📝 `:memo:` - Documentation
- 🔒 `:lock:` - Security fixes
- ⚡ `:zap:` - Performance improvements
- 💄 `:lipstick:` - UI/styling updates

## Example

```
✅ PAY-310 Fix flaky tests with non-zero tax amounts

Tests in TestAddTireServiceIndividual and TestAddTireServiceMultiple
were marked as flaky because they randomly failed when tax amounts
or percentages were generated as zero by Faker.

Solution:
- Added non_zero trait to MoneyFaker with min_value=Decimal('0.01')
- Updated test fixtures to ensure tax amounts and percentages >= 0.01
- Removed @pytest.mark.flaky decorators

Fixes: PAY-310
```
