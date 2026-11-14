Renaming a config entry does not install the satellite plugin a skill
moved to. Read `${CLAUDE_PLUGIN_ROOT}/src/dev10x/core/plugins.yaml`:
each entry under `extracted:` ships as `plugin_names[<entry>]`, and its
skills are listed under `plugins[<entry>]`. The file is the source of
truth, so a table copied here would go stale on the next extraction.
`update-paths` (step 1 of the Step 2 maintenance pass) moves those
skills' script rules to the satellite's directory; its dry run lists
each one as a move, not a removal (GH-1793). `ensure-scripts` and
`ensure-reads` then scan every installed satellite beside core, so a
user who never held the old core rules still gets the satellite's
script and skill-folder grants; a satellite with no cache directory
is skipped (GH-1807).

When the dry run rewrote any name with one of those prefixes, or the
user asks for one of those skills, check `enabledPlugins` in
`~/.claude/settings.json` for `<plugin>@Dev10x-Guru`. If it is
missing, tell the user the skills moved and that running
`claude plugin install <plugin>@Dev10x-Guru` in their shell restores
them (it installs `dev10x` with it if needed). Do not install it for
them: installing a plugin is the user's call.
