"""Independent nodes for the workbench's copied H3 confirmation recipe."""
from .node import ZlyH3ConfirmedDirector

NODE_CLASS_MAPPINGS = {"ZlyH3ConfirmedDirector": ZlyH3ConfirmedDirector}
NODE_DISPLAY_NAME_MAPPINGS = {"ZlyH3ConfirmedDirector": "ZLY H3 Director · Confirmed stages"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
