# Fixes

Each fixed defect and the regression test that keeps it fixed. "fails" means the test fails on the previous
release, so it shows the defect; "guard" means it keeps a fix from being undone. The static tier checks that
every test named here exists.

| Version | Problem | Test | On the previous release |
| --- | --- | --- | --- |
| 3.6.7 | The checkout README, now the GitHub front page, failed the generated-README comparison and the template lint | `test_distribution.Install.test_template_checkout_matches_defaults` | fails |
| 3.6.7 | Projects keep receiving the generated README, not the front page | `test_distribution.Install.test_facade_readme_stays_in_template` | guard |
| 3.6.7 | Two backspace bytes in `rows.py:128` where `\b` was meant | `test_static.SourceBytes.test_no_control_characters` | fails |
| 3.6.7 | A backslash line continuation flattened into spaces in `coverage.py:373` | `test_static.SourceBytes.test_no_collapsed_continuations` | fails |
| 3.6.7 | An invalid escape in a test string, a warning today and an error in a later Python | `test_static.SourceBytes.test_sources_parse_with_the_python_3_10_grammar` | fails |
| 3.6.7 | The manifest drifted from the checkout without notice | `test_static.SourceBytes.test_manifest_matches_the_checkout` | fails |
| 3.6.7 | `release` built a package with a control character in the source | `test_distribution.Release.test_release_refuses_a_control_character` | fails |
| 3.6.7 | `release` built a version that the version table does not list | `test_distribution.Release.test_release_requires_the_version_row` | fails |
| 3.6.7 | `release` ran no self-tests | `test_distribution.Release.test_release_requires_a_full_run_on_this_code` | fails |
| 3.6.7 | A failed release left the manifest stamped | `test_distribution.Release.test_release_restores_the_manifest_when_the_package_check_fails` | fails |
| 3.6.7 | `dist/README.md` did not say which self-tests passed | `test_distribution.Release.test_release_records_the_gate_result` | fails |
| 3.6.7 | Three writers at once lose or duplicate no rows | `test_regressions.Locking.test_three_processes_add_without_losing_rows` | guard |
| 3.6.7 | The fix table names only tests that exist | `test_static.Process.test_fix_table_names_existing_tests` | guard |
| 3.6.7 | An edit could drop an owner rule from AGENTS.md unnoticed | `test_static.OwnerRules.test_agents_md_keeps_owner_rule_anchors` | guard |
| 3.6.7 | A waiting command deleted the lock of a live holder whose generation lagged after a takeover | `test_session.SessionIdentity.test_live_lock_is_not_reclaimed_even_with_an_older_generation` | fails |
| 3.6.7 | Leaving the lock deleted it even after another process had taken it | `test_regressions.Locking.test_l1_release_keeps_a_lock_that_is_not_ours` | fails |
| 3.6.7 | On Windows a process this user may not open was taken for dead, so its lock was reclaimed | `test_regressions.Locking.test_access_denied_counts_as_alive` | fails |
| 3.6.7 | On Windows a waiting command crashed when it deleted a stale lock that another command was reading | `test_regressions.Locking.test_a_stale_lock_that_a_reader_holds_open_is_retried` | fails |
| 3.6.7 | Leaving the lock while another command read it left the lock behind | `test_regressions.Locking.test_release_is_retried_while_a_reader_holds_the_lock` | fails |
| 3.6.7 | On Windows a command crashed when it created the lock while the previous one was still being deleted | `test_regressions.Locking.test_a_lock_create_refused_during_a_delete_is_retried` | fails |
| 3.6.7 | Retiring a requirement that another session's claimed task cites was allowed, then refused with a broken sentence | `test_regressions.Retire.test_p1_retire_requirement_cited_by_claimed_task_is_refused` | fails |
| 3.6.7 | Retiring a feature whose Tasks column holds another session's claimed task was allowed | `test_regressions.Retire.test_p1_retire_feature_whose_tasks_column_holds_claimed_task_is_refused` | fails |
| 3.6.7 | Retiring what only your own task builds on stays allowed | `test_regressions.Retire.test_retiring_what_only_your_own_task_builds_on_is_allowed` | guard |
| 3.6.7 | R1 matches neither R10 nor R12, T2 not T12 | `test_regressions.RetireMatching.test_r1_does_not_match_r10` | guard |
| 3.6.7 | Importing `wslib.rows` or `wslib.runs` before `wslib.ops` failed with a circular import | `test_regressions.Imports.test_every_module_imports_alone` | fails |
| 3.6.7 | After its checkpoint released the workspace, the same session's `verify --done` kept the evidence but did not attach it | `test_regressions.Resume.test_l5_verify_done_after_release_attaches` | fails |
| 3.6.7 | A command that takes the lock twice logged `resume` twice | `test_regressions.Resume.test_l5_one_resume_row` | fails |
| 3.6.7 | `ws note`, `ws reconcile` and `ws snapshot` refused the session that had just released the workspace | `test_regressions.Resume.test_l5_note_reconcile_snapshot_resume` | fails |
| 3.6.7 | With the checkpoint manifest missing, every write passed unchecked | `test_regressions.Resume.test_missing_checkpoint_manifest_does_not_disable_guarded` | fails |
| 3.6.7 | A hand-edited state line let every write pass unchecked | `test_regressions.Guarded.test_invalid_state_line_refuses_every_write` | fails |
| 3.6.7 | A check that stopped at a broken row let every write pass unchecked | `test_regressions.Guarded.test_check_that_stops_early_refuses_every_write` | fails |
| 3.6.7 | The resumed claim is saved with a valid state line, so its first write is still checked | `test_regressions.Resume.test_l5_first_write_after_release_is_validated` | guard |
| 3.6.7 | `--rev` names the revision read before the resume, also across the two locks of a checkpoint | `test_regressions.Resume.test_l5_rev_matches_the_revision_before_resume` | guard |
| 3.6.7 | Cursor conversations were one session to the tool, so the same conversation could not run `ws start` again | `test_regressions.Identity.test_l3_cursor_conversation_resumes_and_another_is_refused` | fails |
| 3.6.7 | A Cursor subagent wrote to the workspace as its parent | `test_regressions.Identity.test_cursor_subagent_conversation_cannot_write` | fails |
| 3.6.7 | A second `ws start` in the owner's window gave no hint that the caller may be the conversation holding the workspace | `test_regressions.Identity.test_l3_refusal_names_the_same_window_case` | fails |
| 3.6.7 | The Cursor turn hook warned another conversation only when the owner had claimed through the brief key | `test_regressions.Identity.test_cursor_turn_hook_names_another_conversation` | fails |
| 3.6.7 | The Cursor chat around a host CLI started from its agent shell could write under that CLI's claim | `test_regressions.Identity.test_a_host_started_from_a_cursor_shell_is_the_session` | fails |
| 3.6.7 | The turn hook warns a conversation that holds nothing, never one with a parallel claim | `test_regressions.ClaimedTurnHook.test_turn_hook_spares_a_conversation_with_a_parallel_claim` | fails |
| 3.6.7 | Tests run inside a host conversation would give every test project that conversation | `test_static.Process.test_test_environment_clears_every_session_variable` | guard |
| 3.6.7 | The last parallel session to leave sealed the workspace with errors outside its tasks | `test_regressions.Parallel.test_p2_last_leaver_with_global_errors_releases_without_seal` | fails |
| 3.6.7 | The main session's seal recorded the tasks of working parallel sessions as accepted, so their stale evidence passed later | `test_regressions.Parallel.test_n1_primary_checkpoint_keeps_parallel_tasks_unsealed` | fails |
| 3.6.7 | A takeover dropped the rows of released parallel sessions with their stop points | `test_regressions.Parallel.test_p3_takeover_keeps_released_parallel_rows` | fails |
| 3.6.7 | A parallel session could not reconcile after the main session released | `test_regressions.Parallel.test_p4_parallel_session_reconciles_after_primary_released` | fails |
| 3.6.7 | A parallel session's snapshot rewrote the main session's card baseline | `test_regressions.Parallel.test_p4_parallel_session_cannot_snapshot` | fails |
| 3.6.7 | `ws start --task` from a session that already worked changed its claim without a clash check | `test_regressions.Parallel.test_p5_repeated_start_task_checks_clashes` | fails |
| 3.6.7 | Repeating `ws start --task` after compaction failed on a task finished meanwhile | `test_regressions.Parallel.test_p5_resumed_start_drops_done_tasks_without_refusing` | fails |
| 3.6.7 | A parallel checkpoint did not log hand edits of its tasks, and later checkpoints would log one edit twice | `test_regressions.Parallel.test_parallel_checkpoint_logs_hand_edits` | fails |
| 3.6.7 | `--writer` with another session's claim label wrote as that session | `test_regressions.Parallel.test_parallel_claim_cannot_be_impersonated_with_writer_flag` | fails |
| 3.6.7 | Each host's hook file was listed in three places that disagreed, and adapters and search-ignore files counted as source | `test_regressions.Hooks.test_h3_every_host_settings_file_is_in_hook_files` | fails |
| 3.6.7 | Enabling Qoder or Qwen hooks turned a READY workspace NOT READY | `test_regressions.Hooks.test_h3_hooks_keep_ready_for_watched_hosts` | fails |
| 3.6.7 | Enabling Gemini hooks changed a watched file without saying so, and a long hook list counted against the adapter size | `test_regressions.Hooks.test_n2_gemini_hooks_print_the_checkpoint_note` | fails |
| 3.6.7 | A checkpoint from an older version reported files the new rules no longer watch as removed | `test_regressions.Hooks.test_rewatch_ignores_files_the_new_rules_exclude` | fails |
| 3.6.7 | An invalid expect pattern was accepted by `ws add` and crashed `ws verify` with a traceback | `test_regressions.Evidence.test_v3_invalid_expect_regex_is_a_clean_error` | fails |
| 3.6.7 | An acceptance written as "`check: ...`" was run as a test | `test_regressions.Evidence.test_v3_backticked_check_is_a_check` | fails |
| 3.6.7 | Test evidence did not count for a check acceptance, so rows read as checks from this version on would lose their evidence | `test_regressions.Evidence.test_n8_old_test_evidence_satisfies_a_check_acceptance` | fails |
| 3.6.7 | `py -3.12 ...` ran the tool's own interpreter, which rejects the version switch | `test_regressions.Evidence.test_v4_py_launcher_version_switch_is_kept` | fails |
| 3.6.7 | `ws brief` and `ws check` wrote the message cache although they are read-only | `test_regressions.Misc.test_u5_brief_with_a_transcript_writes_no_cache` | fails |
| 3.6.7 | A task waiting on a dropped task was offered as ready next, though it could never be marked done | `test_regressions.Misc.test_u7_dropped_dependency_has_one_meaning` | fails |
| 3.6.7 | A dependency cycle also named the tasks that only wait on it | `test_regressions.Misc.test_u7_cycle_names_only_members` | fails |
| 3.6.7 | A snapshot lacked the chat index, the checkpoint manifest and the evidence a restored copy needs | `test_regressions.Misc.test_u7_snapshot_restores_to_a_checkable_workspace` | fails |
| 3.6.7 | The checkpoint linted the card before writing it | `test_regressions.Misc.test_u2_first_checkpoint_has_no_lint_warning` | guard |
| 3.6.7 | Codex gave the SessionEnd hook one second, too short to copy the transcript | `test_regressions.Misc.test_h4_codex_session_end_has_a_timeout` | fails |
| 3.6.7 | The per-turn reminder said credentials are never written to a file, also where the user had chosen "plain" | `test_regressions.Misc.test_u63_turn_reminder_follows_the_credential_rule` | fails |
| 3.6.7 | Hook entries with a quoted, absolute or variable path were not recognized as the tool's own, so enabling hooks again added a second set | `test_regressions.Entry.test_is_ours_recognizes_quoted_absolute_and_variable_commands` | fails |
| 3.6.7 | Hook commands always started with "python", which some machines lack | `test_regressions.Entry.test_x1_hook_command_uses_an_interpreter_that_exists` | fails |
| 3.6.7 | An older Python stopped on ws.py with a traceback instead of saying which version it needs | `test_regressions.Entry.test_x1_python_version_message` | fails |
| 3.6.7 | ws.py stays readable by Python 3.7 to 3.9, or its version message cannot print | `test_static.SourceBytes.test_ws_py_parses_with_the_python_3_7_grammar` | guard |
| 3.6.7 | West of UTC, an edit made with `ws set` in the evening was reported as a hand edit | `test_regressions.Misc.test_hand_edits_use_the_local_date` | fails |
| 3.6.7 | A linked `.agents` folder made ws.py read and write the project it links to | `test_regressions.Misc.test_linked_agents_folder_is_refused` | fails |
| 3.6.7 | `--move-detail` into a new spec folder was always refused | `test_regressions.Misc.test_move_detail_into_a_new_spec_folder` | fails |
| 3.6.7 | The external DeepSeek Harness decoder had no size limit | `test_regressions.Misc.test_dsh_helper_stops_at_the_size_limit` | fails |
| 3.6.7 | A chat from a folder whose name starts with the project's was taken as the project's, and a lowercase drive letter was missed | `test_regressions.Capture.test_c4_mentions_boundary_and_drive_case` | fails |
| 3.6.7 | Scan results cached under the old matching rules were kept | `test_regressions.Capture.test_c4_scan_cache_from_older_rules_is_recomputed` | fails |
| 3.6.7 | An install that failed part way left half its files in the target | `test_distribution.Install.test_i2_install_failure_leaves_the_target_unchanged` | fails |
| 3.6.7 | A broken link in the project's own README.md blocked checkpoints | `test_distribution.Install.test_project_readme_links_are_not_checked` | fails |
| 3.7.0 | A change of the test-output parser would have made the sealed evidence of every project invalid | `test_regressions.Evidence.test_13_rules_1_evidence_stays_valid_after_a_parser_change` | fails |
| 3.7.0 | A summary edited by hand is still rejected under the rules the evidence recorded | `test_regressions.Evidence.test_13_forged_summary_is_still_rejected` | guard |
| 3.7.0 | Evidence read with newer rules than the tool knows was not told apart from a tampered file | `test_regressions.Evidence.test_13_newer_rules_are_refused_with_an_upgrade_hint` | fails |
| 3.7.0 | Rules 1 keep reading evidence exactly as 3.6.x did | `test_regressions.Evidence.test_13_frozen_rules_1_golden_outputs` | guard |
| 3.7.0 | Evidence that passed under older rules but fails under the current ones went unnoticed | `test_regressions.Evidence.test_13_older_rules_are_rechecked_with_a_note` | fails |
| 3.7.0 | An "OK" printed by the program under test made a passing unittest run unreadable | `test_regressions.Evidence.test_v3_program_printing_ok_keeps_the_unittest_summary` | fails |
| 3.7.0 | A log line starting with "FAILED" counted as a test failure | `test_regressions.Evidence.test_failed_log_line_is_not_a_test_failure` | fails |
| 3.7.0 | Enabling Gemini hooks on a released workspace left it NOT READY until a new session checkpointed | `test_upgrade.Rebaseline.test_hooks_enable_on_a_released_workspace_keeps_it_ready` | fails |
| 3.7.0 | A rebaseline takes in template files only, so other drift is still reported | `test_upgrade.Rebaseline.test_rebaseline_keeps_other_drift` | guard |
| 3.7.0 | A rebaseline refuses project files | `test_upgrade.Rebaseline.test_rebaseline_takes_only_template_files` | guard |
| 3.7.0 | A rebaseline waits until the workspace is released | `test_upgrade.Rebaseline.test_rebaseline_needs_a_released_workspace` | guard |
| 3.7.0 | There was no way to take the tool's hooks out of a host settings file | `test_regressions.Install.test_x3_hooks_disable_restores_the_settings_file` | fails |
| 3.7.0 | `install --merge` showed no preview of a merge and kept no copy of the merged files | `test_regressions.Install.test_x3_merge_dry_run_prints_a_diff` | fails |
| 3.7.0 | An install with --allow-modified recorded the template's hashes, not those of the files it copied | `test_regressions.Install.test_manifest_matches_written_files` | fails |
| 3.7.0 | Migrated v2 tasks lost their requirement IDs in CLOSED_ITEMS, so coverage dropped after a migration | `test_distribution.Migration.test_14_migrated_closed_tasks_keep_requirement_ids` | fails |
| 3.7.0 | Coverage counted every requirement ID anywhere in a closed task's text, so "leave R2 for later" verified R2 | `test_distribution.Migration.test_s4_coverage_reads_only_the_requirement_prefix` | fails |
| 3.7.0 | Tasks verified under continuity.v2 counted as verified in v3 without a run | `test_distribution.Migration.test_v2_closed_rows_are_counted_apart` | fails |
