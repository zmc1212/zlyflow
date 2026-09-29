import sys, os, re
path = "frontend/src/director2/panes/UnifiedWorkshopPane.tsx"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace(
    'const load = useCallback(async () => {',
    'const load = useCallback(async (fetchHistory = false) => {'
)

content = content.replace(
    'readWorkshop(projectId, episodeId), getEpisodeProduction',
    'readWorkshop(projectId, episodeId, fetchHistory || script), getEpisodeProduction'
)

# And add the script to dependency array of load
content = content.replace(
    '}, [episodeId, projectId])',
    '}, [episodeId, projectId, script])'
)

# And when clicking the menu item to open the Drawer, trigger load(true)
content = content.replace(
    '{ key: "script", label: "查看采纳剧本", onClick: () => setScript(true) },',
    '{ key: "script", label: "查看采纳剧本", onClick: () => { setScript(true); void load(true); } },'
)

# When polling, it calls void load()
# This is fine, since script will be evaluated as script state.

# In the setView, we must ensure we don't wipe out history if fetchHistory was false but we already have history in view.
# Actually, if we fetch without history, readWorkshop returns history: [], so it WILL wipe out history in the state.
# But since fetchHistory || script is true when the drawer is open, we WILL get history when the drawer is open!
# When the drawer is closed, script is false, so it fetches without history, and wipes out history in state.
# That's perfectly fine! The Drawer is closed anyway!

# Wait, the signature check:
# const viewSig = (w: any) => w ? JSON.stringify({ ... historyCount: w.history?.length }) : ""
# If we wipe out history, w.history?.length becomes 0. viewSig changes, so it updates the state! That is correct.

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
