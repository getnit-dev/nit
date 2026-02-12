# Documentation Adapters

nit can generate documentation (docstrings, API docs, README updates) using language-specific documentation adapters. The doc generation pipeline uses Tree-sitter for AST parsing combined with LLM-powered content generation and memory-based state tracking to detect changes and avoid re-generating unchanged documentation.

## Supported tools

| Adapter | Language | Style |
|---------|----------|-------|
| Sphinx | Python | Google / NumPy docstrings |
| Doxygen | C/C++ | Doxygen comment blocks |
| godoc | Go | Go doc comments |
| JSDoc | JavaScript | JSDoc annotations |
| TypeDoc | TypeScript | TSDoc annotations |
| rustdoc | Rust | Rust doc comments (`///`) |
| MkDocs | Any | Markdown documentation |

## Configuration

Configure documentation generation in `.nit.yml`:

```yaml
docs:
  enabled: true                    # Enable documentation generation
  output_dir: ""                   # Output directory (empty = inline only)
  style: ""                        # Docstring style: google, numpy (auto-detect if empty)
  framework: ""                    # Framework override (auto-detect if empty)
  write_to_source: false           # Write docstrings back into source files
  check_mismatch: true             # Detect doc/code semantic mismatches via LLM
  exclude_patterns: []             # Glob patterns to exclude
  max_tokens: 4096                 # Token budget per file
```

## Usage

Generate documentation with the `docs` command:

```bash
# Generate all documentation types
nit docs --type all

# Generate only docstrings
nit docs --type docstrings

# Write generated docstrings back to source files
nit docs --type docstrings --write-to-source

# Generate docs to an output directory
nit docs --type docstrings --output-dir docs/api

# Override docstring style
nit docs --type docstrings --style google

# Override framework detection
nit docs --type docstrings --framework sphinx

# Run mismatch detection only
nit docs --type docstrings --check-mismatch

# Disable mismatch detection
nit docs --type docstrings --no-check-mismatch

# Generate changelog
nit docs --type changelog

# Update README
nit docs --type readme
```

## Semantic mismatch detection

When `check_mismatch` is enabled (the default), nit uses the LLM to compare existing documentation against the current code and detect mismatches:

- **Missing parameters** — parameters in the signature but not documented
- **Extra parameters** — parameters documented but removed from the signature
- **Wrong return descriptions** — return type/value docs that don't match the code
- **Semantic drift** — descriptions that contradict what the code actually does
- **Stale references** — references to removed functionality

Mismatches are reported with severity levels (`error` or `warning`) and displayed in the CLI output.

## Write-back to source files

When `write_to_source` is enabled, nit writes generated docstrings directly into your source files:

- **Python**: Inserts triple-quoted docstrings inside function/class bodies
- **JavaScript/TypeScript**: Inserts `/** ... */` blocks above declarations
- **C/C++**: Inserts `/** ... */` blocks above declarations
- **Go**: Inserts `// ...` comments above declarations
- **Rust**: Inserts `/// ...` comments above declarations

## Output directory

When `output_dir` is set, nit writes generated documentation as Markdown files to the specified directory, organized by the source file structure. This is useful for generating API reference documentation alongside your source code.

## Style preferences

For Python (Sphinx) documentation, you can specify a preferred docstring style:

- `google` — Google-style docstrings (`Args:`, `Returns:`, `Raises:`)
- `numpy` — NumPy-style docstrings (`Parameters`, `Returns`, `Raises` with underlines)

When the style is empty, nit uses the default combined style.

## Sphinx (Python)

**Detection signals:**

- `docs/conf.py` (Sphinx config)
- `sphinx` in dependencies
- Existing Google or NumPy style docstrings

Generates Google-style or NumPy-style docstrings for Python functions and classes:

```python
def calculate_total(items: list[Item], tax_rate: float = 0.0) -> float:
    """Calculate the total price of items including tax.

    Args:
        items: List of items to total.
        tax_rate: Tax rate as a decimal (e.g., 0.08 for 8%).

    Returns:
        Total price including tax.

    Raises:
        ValueError: If tax_rate is negative.
    """
```

## Doxygen (C/C++)

**Detection signals:**

- `Doxyfile` or `doxygen.cfg`
- Existing `/** */` comment blocks

Generates Doxygen-compatible documentation blocks:

```cpp
/**
 * @brief Calculate the sum of two integers.
 *
 * @param a First operand.
 * @param b Second operand.
 * @return The sum of a and b.
 */
int add(int a, int b);
```

## godoc (Go)

**Detection signals:**

- `go.mod` file
- Existing Go doc comments

Generates Go-style documentation comments:

```go
// Add returns the sum of two integers.
// It handles both positive and negative values.
func Add(a, b int) int {
```

## JSDoc (JavaScript)

**Detection signals:**

- `package.json`
- `.js` source files
- Existing `/** */` JSDoc blocks

## TypeDoc (TypeScript)

**Detection signals:**

- `tsconfig.json`
- `typedoc` in dependencies
- `.ts` source files

## rustdoc (Rust)

**Detection signals:**

- `Cargo.toml`
- Existing `///` doc comments

Generates Rust documentation comments:

```rust
/// Adds two numbers together.
///
/// # Arguments
///
/// * `a` - The first number.
/// * `b` - The second number.
///
/// # Examples
///
/// ```
/// let result = add(2, 3);
/// assert_eq!(result, 5);
/// ```
pub fn add(a: i32, b: i32) -> i32 {
```

## MkDocs

**Detection signals:**

- `mkdocs.yml` file
- `docs/` directory with Markdown files

The MkDocs adapter generates and updates Markdown documentation files rather than inline docstrings.
