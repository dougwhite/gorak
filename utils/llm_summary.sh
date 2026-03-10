#!/bin/bash

# Summarize all project files in a markdown-friendly format for quickly communicating the entire project
# to an LLM for assistance / code review. Or just to quickly generate context for a ChatGPT/Grok project
# so you don't need to constantly re-explain important details every time the context window is reset.

# Determine script directory and project root
script_dir="$(dirname "$(realpath "$0")")"
project_root="$(dirname "$script_dir")"  # Assumes utils/ is directly under project_root

# Output file path
output_file="$project_root/.llm/summary.md"
mkdir -p "$(dirname "$output_file")"  # Create .llm dir if it doesn't exist

# Redirect all output to the file (overwrites existing file)
exec > "$output_file"

# Patterns to ignore (supports bash glob patterns like *.lock or tests/*)
ignore_patterns=("uv.lock" ".gitignore" "**/.gitkeep" ".python-version" "*.xml" "*.4gl" "**/__init__.py" "README.md" "utils/*")

# Prepend summary.md with the contents of the README.md
# Adding the readme to LLM project context works better than prepending it to each new context window
# Also the human readable version requires some modification to transform it into a concise
# llm optimized instruction set - so for now we've removed this and left it up to the user.
# cat "$project_root/README.md"

# Get all tracked files in the repo
files=$(git ls-files)

for file in $files; do
    # Check if file matches any ignore pattern
    skip=0
    for pattern in "${ignore_patterns[@]}"; do
        if [[ "$file" == $pattern ]]; then
            skip=1
            break
        fi
    done
    if [ $skip -eq 1 ]; then
        continue
    fi
    
    # Output filename in single backticks
    echo "\`$file\`"
    
    # Determine language based on extension
    ext="${file##*.}"
    lang=""
    if [ "$ext" = "py" ]; then
        lang="python"
    elif [ "$ext" = "toml" ]; then
        lang="toml"
    fi
    
    # Output file contents in triple backticks with language if applicable
    echo "\`\`\`$lang"
    cat "$file" | sed 's/```/\\```/g'
    echo ""
    echo "\`\`\`"
    
    # Blank line between files
    echo ""
done

# Output the tree structure of the program
echo "Project layout"
echo "\`\`\`"
tree --gitignore
echo "\`\`\`"
echo ""

# Output the todo
echo "Todo"
echo "=========="
cat "$project_root/todo"