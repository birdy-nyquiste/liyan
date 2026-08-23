# Let the user name the author when publishing

The author name sent to a publication platform is typed by the user in the publishing flow, not derived from the 发布目标. A destination grants access; it does not decide whose byline appears on the result. Configuring an author per target would mean a near-duplicate target for every writer sharing one Blog, and editing deployment configuration whenever a writer joins or wants a different byline — while the author is precisely the part of a submission that belongs to the person publishing.

The name is trimmed and required before a snapshot is locked, because LSForum Blog treats one `author.name` as one author across submissions: untrimmed spacing would silently create a second author, and a blank name is rejected by the platform. The confirmation screen stays read-only in every other respect, so the author is the only thing it can change.

This reverses what Notion's Function Spec §6.3 and the Phase 1 PRD describe, both of which take the author from the publication target. Those documents are the ones that need to change.
