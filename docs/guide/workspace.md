# Workspace and history

Open **Search**, **Bibliometrics**, or **Reviews** from the left sidebar. Use the module’s history to reopen a saved search, analysis, or review.

| Module | Subfunctions | Saved object |
| --- | --- | --- |
| Search | Search settings, Run progress, Results | One search run |
| Bibliometrics | Overview, Keywords, Paper relations, Data quality | One independent corpus analysis |
| Reviews | Papers, Outline, Draft, Citation evidence | One editable review |

The sidebar lists the current module’s history. The header button hides or shows the entire sidebar; on small screens it opens as a dismissible drawer. Use the new-record button to start a draft, the magnifying glass beside the history heading to search records, and **All** to open the current module’s full history list. A new draft is not a history record until it is saved or submitted.

The full history list provides record menus for rename, export, and delete. A title change does not rewrite the research question, review topic, or original execution settings. Deletion has a confirmation dialog. Active tasks cannot be deleted while they are running.

The sidebar footer contains **Settings**, documentation, and the account menu. Settings has four sections: **Model APIs**, **Data sources**, **General**, and **User**, at `/settings/models`, `/settings/sources`, `/settings/general`, and `/settings/user`. Return to a module through the sidebar or browser Back button.

Add or edit a model connection in its dialog and click **Save**. In a data-source configuration dialog, **Save** persists the key and options; **Test connection** also saves them before testing. A failed test or subsequently cancelling the dialog does not undo that save. Default model and ranking selections save when changed. They apply to new drafts; saved runs keep their execution settings. Review model settings apply to the current review and cannot change during generation. The **User** page shows the local data location and provides saved-key and history management. Language is available in General, the header, and the account menu; the online account menu also exposes account and service actions.

## Inputs, saved keys, and browser state

- Unsaved form inputs and drafts are temporary browser memory and disappear on reload. **Test connection** in the model connection dialog sends the draft to the server without saving it. In a data-source configuration dialog, the same action saves first; the input is then saved configuration, even if the test fails. **Test** and **Test all** in the source table use the configured credentials.
- Saved model connections and data-source keys persist on the server. Community encrypts secret values in its database using the adjacent `credentials.master.key`; refreshing or restarting does not clear them. Settings returns key status and masked suffixes, not saved plaintext keys.
- Submitted tasks may retain a separate encrypted credential copy for execution and recovery. **Settings → User → Clear saved keys** deletes saved connections and source keys, but does not affect already-submitted tasks.
- Browser storage contains preferences such as language and sidebar visibility, not API keys. Clearing browser storage or reloading does not delete server-side keys.

Citation maps are available under the review's **Citation evidence → Paper relations**. Old direct map and history links remain usable.

Switching modules retains loaded results, filters, selections, and scroll position in this browser session. The result cache keeps the ten most recently visited runs; reloading clears this temporary state. Unsaved outline and paragraph edits prompt before leaving, so you can keep editing or discard them. Save edits before reloading.

New reviews save the available source citation map with their evidence, so they can still show it after source-search deletion. Older reviews without that snapshot depend on the source record for this graph. Saved analyses always retain their own corpus snapshots.
