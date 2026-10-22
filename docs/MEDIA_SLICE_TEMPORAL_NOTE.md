# Temporal note

`MediaPreparationWorkflow` stays on the main Temporal workflow queue, while the untrusted byte-processing activity is explicitly dispatched to the dedicated media activity queue. Result delivery returns to the main worker so the media worker does not need Telegram credentials.
