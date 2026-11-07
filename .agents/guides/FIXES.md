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
| 3.6.7 | An invalid escape in a test string, a warning today and an error in a later Python | `test_static.SourceBytes.test_sources_parse_with_the_python_3_9_grammar` | fails |
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
| 3.7.0 | Projects had no upgrade command: files were copied by hand, and guides the project had edited were overwritten | `test_upgrade.Upgrade.test_replaces_unmodified_and_keeps_modified_guides` | fails |
| 3.7.0 | Hook commands written by an older release were never updated in a project; an upgrade rewrites only the tool's entries | `test_upgrade.Upgrade.test_regenerates_only_our_hook_entries` | fails |
| 3.7.0 | An upgrade dry run writes nothing, not even the cache | `test_upgrade.Upgrade.test_dry_run_writes_nothing` | guard |
| 3.7.0 | An upgrade refuses tool code the project changed, so the tool never mixes two versions | `test_upgrade.Upgrade.test_refuses_modified_tool_code` | guard |
| 3.7.0 | An upgrade keeps the project's rules under "## Project rules" in AGENTS.md | `test_upgrade.Upgrade.test_merges_the_project_rules_section` | guard |
| 3.7.0 | An upgrade leaves .agents/hooks.json and docs/ as they are | `test_upgrade.Upgrade.test_keeps_hooks_json_and_docs` | guard |
| 3.7.0 | A second upgrade changes nothing | `test_upgrade.Upgrade.test_is_idempotent` | guard |
| 3.7.0 | An upgrade stopped by an error puts every file back; one stopped by a kill is put back byte for byte by --rollback | `test_upgrade.Upgrade.test_interrupted_then_rollback_restores_bytes` | guard |
| 3.7.0 | A rollback after sessions wrote needs --force and keeps their state | `test_upgrade.Upgrade.test_rollback_after_new_work_needs_force_and_keeps_the_state` | guard |
| 3.7.0 | A new tool that fails on the project is rolled back | `test_upgrade.Upgrade.test_a_new_tool_that_fails_on_the_project_is_rolled_back` | guard |
| 3.7.0 | A restore that fails exits 3 and names the rollback to run | `test_upgrade.Upgrade.test_a_failed_restore_exits_3_and_names_the_rollback` | guard |
| 3.7.0 | Both 3.6.6 manifest shapes, and a project without a manifest, upgrade correctly | `test_upgrade.Upgrade.test_bases_from_zip_and_head_manifests` | guard |
| 3.7.0 | An upgrade refuses a workspace a session owns | `test_upgrade.Upgrade.test_refuses_an_owned_workspace` | guard |
| 3.7.0 | An upgrade refuses a continuity.v2 workspace and names the migrate command | `test_upgrade.Upgrade.test_refuses_v2_and_names_migrate` | guard |
| 3.7.0 | An upgrade refuses a project whose .agents folder is a link | `test_upgrade.Upgrade.test_linked_agents_folder_is_refused` | guard |
| 3.7.0 | upgrade --scan lists the workspaces under a folder and writes nothing | `test_upgrade.Upgrade.test_scan_lists_versions_and_writes_nothing` | guard |
| 3.7.0 | A rebaseline cannot drop the entry of a project file, or of a file that still exists | `test_upgrade.Rebaseline.test_removed_entries_are_template_files_that_are_gone` | guard |
| 3.7.0 | Nothing told a session that the host it runs in had no hooks in the project, so new sessions started without the brief | `test_doctor.Doctor.test_missing_hooks_of_the_host_that_runs_it` | fails |
| 3.7.0 | Hooks that ran another folder's ws.py, as in a copied project, went unnoticed | `test_doctor.Doctor.test_hooks_that_run_another_projects_tool` | fails |
| 3.7.0 | Tool files that differ from the installed manifest, a mix of two versions, went unnoticed | `test_doctor.Doctor.test_tool_files_that_differ_from_the_manifest` | fails |
| 3.7.0 | ws doctor writes nothing and finds no problem in a sound project | `test_doctor.Doctor.test_a_healthy_project_has_no_problems_and_nothing_is_written` | guard |
| 3.7.0 | A rollback to 3.6.x did not say which evidence the older tool would refuse | `test_regressions.Evidence.test_13_evidence_rules_1_reads_differently_is_listed_for_a_rollback` | fails |
| 3.7.0 | The two-window tests failed under a Python whose folder is not on PATH, such as one installed by uv | `test_field.Windows.test_a_window_without_a_session_variable_cannot_claim_twice` | fails |
| 3.8.0 | A full stop after a path in Scope hid the path, so the task held the whole tree | `test_v38.Scope.test_17_a_full_stop_does_not_hide_the_path` | fails |
| 3.8.0 | Paths with letters outside ASCII were cut at the first such letter | `test_v38.Scope.test_17_paths_in_any_script` | fails |
| 3.8.0 | Any word in Scope was tried as a file name with .py added, so "login module" claimed login.py | `test_v38.Scope.test_17_words_are_not_turned_into_files` | fails |
| 3.8.0 | The "check:" prefix of an acceptance was read as check.py when such a file existed | `test_v38.Scope.test_17_the_check_prefix_is_not_a_path` | fails |
| 3.8.0 | Claims also took the paths of the acceptance command, so two tasks sharing a test could not run in parallel | `test_v38.Scope.test_17_claims_read_only_the_scope` | fails |
| 3.8.0 | Staleness reads the Scope paths plus the files the acceptance runs, including a unittest module and a pytest node | `test_v38.Scope.test_17_staleness_adds_the_files_the_acceptance_runs_and_claims_do_not` | fails |
| 3.8.0 | There was no way to name a file a task creates, a shared resource apart from paths, or the whole tree on purpose | `test_v38.Scope.test_17_new_resource_and_tree` | fails |
| 3.8.0 | A task whose Scope was prose naming no path was accepted and silently held the whole tree | `test_v38.Scope.test_17_add_refuses_prose_and_notes_a_planned_file` | fails |
| 3.8.0 | Rows written before that refusal are flagged, not refused | `test_v38.Scope.test_17_an_old_prose_scope_gets_a_hint_not_a_refusal` | fails |
| 3.8.0 | A sealed task whose files changed later stayed verified, and checkpoint and check --ready still said READY | `test_v38.Regression.test_18_a_change_after_sealing_names_the_task_and_the_file` | fails |
| 3.8.0 | There was no way to run every stale task again in one command | `test_v38.Regression.test_18_verify_stale_runs_the_acceptance_again` | fails |
| 3.8.0 | A project could not choose to be only warned about a regression after sealing | `test_v38.Regression.test_18_the_warn_setting_keeps_ready` | fails |
| 3.8.0 | The first session after an upgrade only warns about regressions found by the newer check; the next one is refused | `test_v38.Regression.test_18_the_first_session_after_an_upgrade_only_warns` | fails |
| 3.8.0 | The brief counted the requirements of a stale task as verified | `test_v38.Regression.test_18_the_verified_count_leaves_out_a_stale_task` | fails |
| 3.8.0 | A change inside a done task's scope counted as registered work even after it made that task's evidence stale | `test_v38.Regression.test_18_a_change_inside_a_stale_task_is_unregistered_work` | fails |
| 3.8.0 | Evidence of a task moved to CLOSED_ITEMS could be edited or deleted without notice | `test_v38.Regression.test_18_evidence_of_a_compacted_task_stays_sealed` | fails |
| 3.8.0 | A test weakened between a task's first run and its accepted one went unmentioned at the checkpoint | `test_v38.Delivery.test_19_a_test_weakened_after_a_failed_run_is_listed` | fails |
| 3.8.0 | A changed run command and a verify with --because went unmentioned at the checkpoint | `test_v38.Delivery.test_19_another_command_and_because_are_listed` | fails |
| 3.8.0 | A checkpoint did not say what the work rests on: the saved state, test or check evidence, and whether the host was tried | `test_v38.Delivery.test_21_a_checkpoint_states_what_the_delivery_rests_on` | fails |
| 3.8.0 | Coverage files written by a run, such as .coverage and coverage.xml, made the run rejected as a change to watched files | `test_v38.Runners.test_20_coverage_files_a_run_writes_do_not_reject_it` | fails |
| 3.8.0 | Output whose summary is not read was rejected without pointing to a report | `test_v38.Runners.test_20_unread_output_points_to_a_report` | fails |
| 3.8.0 | The brief showed only the last five retired rows, each cut to 50 characters | `test_v38.Prohibitions.test_u3_seven_retired_rows_all_appear` | fails |
| 3.8.0 | Past its size budget the brief gives the count of retired rows and the command that lists them all | `test_v38.Prohibitions.test_u3_past_the_budget_the_count_and_the_command_are_given` | fails |
| 3.8.0 | The brief showed only the first eight preferences | `test_v38.Prohibitions.test_u3_all_preferences_appear` | fails |
| 3.8.0 | ws add and ws set gave the agent no line to tell the user what was recorded | `test_v38.TurnRecord.test_x7_add_and_set_print_a_line_to_relay` | fails |
| 3.8.0 | The prompt hook did not say what the previous turn recorded, or that it recorded nothing | `test_v38.TurnRecord.test_x7_the_turn_hook_says_what_the_previous_turn_recorded` | fails |
| 3.8.0 | There was no view of user messages beside the rows or reasons that account for them | `test_v38.Review.test_x8_review_puts_each_message_beside_its_record` | fails |
| 3.8.0 | Six rules of the first contract had been deleted without the owner's agreement, and two needed new wording (owner decision D3) | `test_v38.Contract.test_29_the_contract_holds_the_restored_rules_in_no_more_bytes` | fails |
| 3.8.0 | The per-turn reminder did not carry the evidence rule, which compaction tends to drop | `test_v38.Contract.test_29_the_turn_reminder_carries_the_evidence_rule` | fails |
| 3.8.0 | The list of ways of working the owner ruled out stayed in the maintainer's files, so new projects never got it | `test_v38.Contract.test_29_a_new_project_lists_what_is_not_adopted` | fails |
| 3.8.0 | A message the user marked as discussion could still turn into numbered requirements, and ideas had no command | `test_v38.Modes.test_30_a_discussion_turn_gets_no_requirement_id` | fails |
| 3.8.0 | A message the user marked read-only did not stop ws writes in that turn | `test_v38.Modes.test_30_a_read_only_turn_writes_nothing` | fails |
| 3.8.0 | The prompt hook did not tell the agent that the user marked a message as a confirmation | `test_v38.Modes.test_30_a_confirmation_is_named` | fails |
| 3.9.0 | Python 3.9, the python3 that comes with macOS, was refused by the version gate (owner decision D0) | `test_regressions.Entry.test_x1_python_version_message` | fails |
| 3.9.0 | Upgrade and snapshot files were written with a keyword argument that Python 3.9 does not have | `test_static.SourceBytes.test_no_call_needs_a_python_newer_than_3_9` | fails |
| 3.9.0 | An empty lock file left by a command killed while writing it blocked every command for 60 seconds | `test_v39.Lock.test_22_an_empty_lock_file_from_a_crash_does_not_block` | fails |
| 3.9.0 | The READY check counted the lock of the process that ran it | `test_v39.Lock.test_22_the_ready_check_does_not_count_its_own_lock` | fails |
| 3.9.0 | A drive that cannot lock files gave no way out | `test_v39.Lock.test_22_a_drive_that_cannot_lock_names_the_way_out` | fails |
| 3.9.0 | A killed holder frees the system lock at once | `test_v39.Lock.test_22_a_killed_holder_frees_the_lock_at_once` | guard |
| 3.9.0 | WS_LOCK=legacy uses the lock file of 3.8 for this version | `test_v39.Lock.test_22_ws_lock_legacy_uses_the_older_lock_file` | guard |
| 3.9.0 | Eight concurrent writers lose and duplicate no row | `test_v39.Lock.test_22_eight_writers_get_unique_ids_and_lose_no_row` | guard |
| 3.9.0 | Who may run which write command was decided in five places; one table now decides it, and PROTOCOL prints that table | `test_v39.Permits.test_23_each_identity_may_run_what_the_table_says` | guard |
| 3.9.0 | The permission table in PROTOCOL could drift from the commands | `test_static.Process.test_protocol_prints_the_permission_table_the_commands_enforce` | guard |
| 3.9.0 | A parallel session could change or verify a task it had not claimed; its release left that task out, and the next main checkpoint stuck on it | `test_v39.Permits.test_23_p8_a_parallel_session_touches_only_tasks_in_its_claim` | fails |
| 3.9.0 | A parallel session could not drop its own task while the card named it: the status was refused, and so was the card | `test_v39.Permits.test_23_p8_a_dropped_task_leaves_the_card` | fails |
| 3.9.0 | Verify was rejected when another session edited files inside its own claim during the run | `test_v39.Permits.test_23_p7_verify_ignores_edits_inside_another_sessions_claim` | fails |
| 3.9.0 | A session that claimed with the --session key the hook prints lost that identity at the next write command, which did not accept --session | `test_v39.Permits.test_23_p6_a_session_key_tells_two_conversations_in_one_window_apart` | fails |
| 3.9.0 | Claude Code, Codex and Gemini saved a turn only in the Stop hook, after the checkpoint had released the workspace, so a READY workspace failed at once | `test_v39.Messages.test_24_ready_survives_the_stop_hook_that_copies_the_turn` | fails |
| 3.9.0 | A user message saved after the checkpoint overturned READY; it is now left to the next session | `test_v39.Messages.test_24_a_message_saved_after_the_seal_waits_for_the_next_session` | fails |
| 3.9.0 | The same sentence in two sessions had one message ID, so the second was never reconciled | `test_v39.Messages.test_24_the_same_sentence_in_two_sessions_is_reconciled_in_each` | fails |
| 3.9.0 | Reconcile rows of 3.8 stay valid when the transcript is written again | `test_v39.Messages.test_24_marks_of_3_8_stay_valid_when_the_transcript_is_written_again` | guard |
| 3.9.0 | A lone "no", "yes", "可以" or "行" was skipped as small talk, although it may answer a question | `test_v39.Messages.test_24_yes_and_no_are_reconciled_like_other_messages` | fails |
| 3.9.0 | A message ID was the hash of the redacted text, so the host's copy of a turn or a change of redaction rules reopened the message | `test_v39.Messages.test_24_the_stop_hook_keeps_the_id_when_the_host_copy_adds_to_the_typed_text` | fails |
| 3.9.0 | A transcript missing from INDEX.md was never read, while reconcile said every message was reconciled | `test_v39.Messages.test_24_a_transcript_missing_from_the_index_is_reported` | fails |
| 3.9.0 | One "ws reconcile all" closed every open message without naming how many | `test_v39.Messages.test_24_reconcile_all_names_how_many_it_marks` | fails |
| 3.9.0 | With the Stop nudge on, a turn that only answered a question was asked to record it | `test_v39.Messages.test_24_the_stop_nudge_lets_a_pure_question_pass` | fails |
| 3.9.0 | Only the BEGIN line of a private key was removed; its key lines stayed | `test_v39.Redaction.test_27_a_private_key_goes_as_one_block` | fails |
| 3.9.0 | Invisible characters were removed only from a line with no other credential, so a second one hidden by a soft hyphen stayed (appendix A6) | `test_v39.Redaction.test_27_invisible_characters_are_removed_before_matching_and_kept_elsewhere` | fails |
| 3.9.0 | JSON strings were redacted without their keys, so "password" and "secret_key" values stayed in the raw copy (appendix A6) | `test_v39.Redaction.test_27_a_json_key_says_its_string_is_the_secret` | fails |
| 3.9.0 | "账号admin 密码admin123", a password in a sentence, sshpass -p, mysql -p and a hex key after "api key" were kept | `test_v39.Redaction.test_27_chinese_labels_sentences_and_command_lines` | fails |
| 3.9.0 | "Password: minimum 8 characters", "Release key: v2.3.1-beta" and "S3 key: exports/2026/data.csv" were rewritten as [REDACTED] for good | `test_v39.Redaction.test_27_explanatory_text_is_left_alone` | fails |
| 3.9.0 | ws check did not scan the transcripts in docs/chats | `test_v39.Redaction.test_27_ws_check_scans_the_saved_transcripts` | fails |
| 3.9.0 | "plain" kept every credential as written everywhere, transcripts included; it now applies only to the files credential_files names (owner decision D2) | `test_v39.Redaction.test_27_d2_plain_keeps_credentials_only_in_the_files_the_owner_names` | fails |
| 3.9.0 | In ask mode a credential is redacted and no write is refused (owner decision D2) | `test_v39.Redaction.test_27_ask_mode_refuses_no_write` | guard |
