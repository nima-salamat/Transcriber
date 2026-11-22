"""Modular native PySide6 components for the Transcriber AI workspace."""
from .activity_widget import AgentActivityWidget
from .composer import MessageComposer
from .conversation_view import ConversationView
from .header import ConversationHeader
from .message_renderer import SafeMarkdownBrowser
from .message_widget import MessageWidget
from .panel import AssistantPanel
from .sidebar import AssistantSidebar

__all__ = [
    "AgentActivityWidget",
    "AssistantPanel",
    "AssistantSidebar",
    "ConversationHeader",
    "ConversationView",
    "MessageComposer",
    "MessageWidget",
    "SafeMarkdownBrowser",
]
