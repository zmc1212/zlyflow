"""Blender startup script: enable the local MCP addon and start its socket."""

import bpy

bpy.ops.preferences.addon_enable(module="blender_mcp")
bpy.context.scene.blendermcp_port = 9876
bpy.ops.blendermcp.start_server()
print("BLENDER_MCP_READY localhost:9876")
