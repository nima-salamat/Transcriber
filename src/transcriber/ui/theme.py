"""Qt stylesheet generated from the central semantic design-token palette."""

from __future__ import annotations

from transcriber.ui.design.tokens import RADII, TYPOGRAPHY, get_tokens


def stylesheet(theme: str) -> str:
    c = get_tokens(theme).colors
    return f"""
    QWidget {{
        color: {c['text']};
        font-family: {TYPOGRAPHY['family']};
        font-size: {TYPOGRAPHY['body']}px;
        outline: none;
    }}
    QMainWindow, QDialog {{ background: {c['window']}; }}
    QWidget#Root {{ background: {c['window']}; }}
    QFrame#Sidebar {{
        background: {c['surface_2']};
        border: 0;
        border-right: 1px solid {c['border']};
    }}
    QFrame#TopBar {{
        background: {c['window']};
        border: 0;
        border-bottom: 1px solid {c['border']};
    }}
    QLabel#SidebarMark {{
        background: transparent;
        border: 0;
        padding: 0;
    }}
    QLabel#SidebarBrand {{
        color: {c['text']};
        font-size: 17px;
        font-weight: 750;
    }}
    QLabel#SidebarTagline {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 650;
        letter-spacing: 1px;
        padding: 0 2px 5px 2px;
    }}
    QLabel#SidebarSectionLabel {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 750;
        letter-spacing: 1.1px;
        padding: 9px 9px 4px 9px;
    }}
    QLabel#SidebarLocalStatus {{
        color: {c['success']};
        font-size: 10px;
        font-weight: 750;
        padding: 5px 3px 1px 3px;
    }}
    QLabel#SidebarVersion {{
        color: {c['muted']};
        font-size: 10px;
        padding: 0 3px;
    }}
    QScrollArea#SidebarNavigationScroll {{
        background: transparent;
        border: 0;
    }}
    QScrollArea#SidebarNavigationScroll > QWidget > QWidget {{
        background: transparent;
    }}
    QWidget#SidebarNavigationContent {{
        background: transparent;
    }}
    QLabel#ToolbarPageTitle {{
        color: {c['text']};
        font-size: 18px;
        font-weight: 600;
    }}
    QWidget#PageHeaderCopy {{
        background: transparent;
    }}
    QLabel#PageDescription {{
        color: {c['muted']};
        font-size: 12px;
    }}
    QLabel#PageEmptyState {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px dashed {c['border']};
        border-radius: 12px;
        padding: 22px;
        font-size: 12px;
    }}
    /* Recorder and player controls use the shared semantic design tokens. */
    QLabel#RecorderMainTimer {{
        color: {c['text']};
        font-size: 42px;
        font-weight: 750;
        letter-spacing: 1px;
        padding: 0;
    }}
    QLabel#RecordingStatus {{
        background: {c['surface_2']};
        color: {c['muted']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 6px 11px;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.6px;
    }}
    QLabel#RecordingStatus[state="ready"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#RecordingStatus[state="recording"], QLabel#RecordingStatus[state="error"] {{
        color: {c['danger']};
        border-color: {c['danger']};
    }}
    QLabel#RecordingStatus[state="paused"] {{
        color: {c['warning']};
        border-color: {c['warning']};
    }}
    QLabel#RecordingStatus[state="saved"] {{
        color: {c['accent']};
        border-color: {c['accent']};
    }}
    QPushButton#RecordPrimary {{
        background: {c['danger']};
        color: white;
        /* Keep the border width constant; the recording pulse only changes its color. */
        border: 3px solid transparent;
        border-radius: 15px;
        padding: 0 20px;
        font-size: 14px;
        font-weight: 750;
        min-height: 54px;
    }}
    QPushButton#RecordPrimary:hover {{
        background: {c['danger']};
        border-color: {c['danger']};
    }}
    QPushButton#RecordPrimary[state="paused"] {{
        background: {c['warning']};
        border-color: {c['warning']};
        color: {c['window']};
    }}
    QPushButton#RecordPrimary:disabled {{
        background: {c['surface_2']};
        border-color: {c['border']};
        color: {c['muted']};
    }}
    QPushButton#RecordPrimary[pulse="true"] {{
        border-color: rgba(225, 75, 91, 0.30);
    }}
    QPushButton#StopRecording {{
        background: {c['danger']};
        border: 1px solid {c['danger']};
        border-radius: 27px;
        min-width: 54px;
        max-width: 54px;
        min-height: 54px;
        max-height: 54px;
        padding: 0;
    }}
    QPushButton#StopRecording:hover {{
        background: {c['danger']};
        border-color: {c['danger']};
    }}
    QPushButton#StopRecording:disabled {{
        background: {c['surface_2']};
        border-color: {c['border']};
    }}
    QPushButton#RecordingPreviewButton, QPushButton#AudioSkipButton {{
        background: {c['surface_2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 22px;
        padding: 0;
        min-width: 42px;
        max-width: 46px;
        min-height: 42px;
        max-height: 46px;
    }}
    QPushButton#RecordingPreviewButton:hover, QPushButton#AudioSkipButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QWidget#RecordingWaveform, QWidget#AudioLibraryWaveform {{
        background: transparent;
        border: 0;
    }}
    QLabel#AudioPlayerTitle {{
        color: {c['text']};
        font-size: 22px;
        font-weight: 750;
    }}
    QLabel#AudioPlayerPosition {{
        color: {c['text']};
        font-size: 25px;
        font-weight: 750;
    }}
    QPushButton#AudioPlayPrimary {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 1px solid {c['primary']};
        border-radius: 13px;
        padding: 8px 20px;
        min-width: 56px;
        min-height: 48px;
    }}
    QPushButton#AudioPlayPrimary:hover {{
        background: {c['primary_hover']};
        border-color: {c['primary_hover']};
    }}
    QPushButton#AudioPlayPrimary:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
        border-color: {c['border']};
    }}
    QFrame#RecordingListCard {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QFrame#RecordingListCard:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QFrame#RecordingListCard[selected="true"] {{
        background: {c['surface']};
        border-color: {c['accent']};
    }}
    QPushButton#RecordingItemTitle {{
        color: {c['text']};
        background: transparent;
        border: 0;
        border-radius: 5px;
        padding: 2px 1px;
        text-align: left;
        font-weight: 700;
    }}
    QPushButton#RecordingItemTitle:hover {{
        color: {c['accent']};
        background: transparent;
        border: 0;
    }}
    QPushButton#RecordingItemTitle:disabled {{
        color: {c['muted']};
        background: transparent;
    }}
    QPushButton#RecordingItemPlayButton {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 17px;
        padding: 0;
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
    }}
    QPushButton#RecordingItemPlayButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['border_hover']};
        color: {c['text']};
    }}
    QPushButton#RecordingItemPlayButton:disabled {{
        color: {c['muted']};
        background: {c['surface']};
        border-color: {c['border']};
    }}
    QLabel#RecordingListEmptyState {{
        color: {c['muted']};
        background: transparent;
        padding: 28px 18px;
        font-size: 12px;
    }}
    QFrame#Card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: {RADII['xl']}px;
    }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#PageTitle {{ color: {c['text']}; font-size: {TYPOGRAPHY['heading']}px; font-weight: 600; }}
    QLabel#SectionTitle {{ font-size: {TYPOGRAPHY['section']}px; font-weight: 600; }}
    QLabel#HomeEyebrow {{
        color: {c['muted']};
        font-size: {TYPOGRAPHY['small']}px;
        font-weight: 600;
        letter-spacing: 0.8px;
    }}
    QLabel#HomeHeroTitle {{
        color: {c['text']};
        font-size: 24px;
        font-weight: 600;
    }}
    QLabel#StatValue {{
        color: {c['text']};
        font-size: 26px;
        font-weight: 600;
    }}
    QLabel#AssistantTitle {{ font-size: 17px; font-weight: 700; }}
    QLabel#AssistantEyebrow {{ color: {c['muted']}; font-size: 10px; font-weight: 750; letter-spacing: 1px; }}
    QLabel#AssistantProject {{ font-size: 12px; font-weight: 600; }}
    QLabel#AssistantStatus {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 5px 8px;
        font-size: 10px;
        font-weight: 650;
    }}
    QLabel#AssistantStatus[state="connected"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#AssistantStatus[state="connecting"] {{ color: {c['warning']}; }}
    QLabel#AssistantStatus[state="error"] {{ color: {c['danger']}; border-color: {c['danger']}; }}
    QFrame#AssistantContext, QFrame#AssistantComposer, QFrame#AssistantVoicePanel,
    QFrame#AssistantSettingsCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#AssistantSectionTitle {{ font-size: 14px; font-weight: 700; }}
    QWidget#AssistantConversationPage, QWidget#AssistantSettingsPage,
    QWidget#AssistantSettingsContent {{ background: transparent; }}
    QScrollArea#AssistantSettingsScroll {{ background: transparent; border: 0; }}
    QPushButton#AssistantSettingsButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 0;
        font-size: 20px;
        min-width: 36px;
        max-width: 40px;
        min-height: 36px;
        max-height: 40px;
    }}
    QPushButton#AssistantSettingsButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QPushButton#AssistantNewChatButton {{
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 7px 11px;
        font-size: 11px;
        font-weight: 650;
    }}
    QPushButton#AssistantNewChatButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QFrame#CommandPalettePopup {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 16px;
    }}
    QLineEdit#CommandPaletteSearch {{
        background: {c['input']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        padding: 11px 13px;
        font-size: 13px;
    }}
    QLineEdit#CommandPaletteSearch:focus {{
        border-color: {c['focus']};
    }}
    QListWidget#CommandPaletteResults {{
        background: transparent;
        border: 0;
        padding: 2px;
    }}
    QListWidget#CommandPaletteResults::item {{
        background: {c['surface_2']};
        border: 1px solid transparent;
        border-radius: 9px;
        padding: 11px 12px;
        margin: 2px 0;
    }}
    QListWidget#CommandPaletteResults::item:hover {{
        background: {c['surface_hover']};
    }}
    QListWidget#CommandPaletteResults::item:selected {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QFrame#AssistantComposer {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 18px;
    }}
    QToolButton#AssistantModelPickerButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        color: {c['text']};
        padding: 8px 11px;
        min-width: 0;
        min-height: 24px;
        font-weight: 650;
        text-align: left;
    }}
    QToolButton#AssistantModelPickerButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QFrame#AssistantModelPickerPopup {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 13px;
    }}
    QLabel#AssistantModelPickerCaption {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 750;
        letter-spacing: 1px;
    }}
    QLabel#AssistantModelPickerMenuStatus {{
        color: {c['muted']};
        font-size: 11px;
        padding-top: 3px;
    }}
    QLabel#AssistantModelConnectionStatus {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 650;
        padding-left: 2px;
    }}
    QLabel#AssistantModelConnectionStatus[state="connected"] {{
        color: {c['success']};
    }}
    QLabel#AssistantModelConnectionStatus[state="connecting"] {{
        color: {c['warning']};
    }}
    QLabel#AssistantModelConnectionStatus[state="error"] {{
        color: {c['danger']};
    }}
    QProgressBar#AssistantConnectionSpinner {{
        border: 0;
        background: transparent;
        min-width: 16px;
        max-width: 16px;
        min-height: 16px;
        max-height: 16px;
    }}
    QProgressBar#AssistantConnectionSpinner::chunk {{
        background: {c['accent']};
        border-radius: 7px;
    }}
    QLabel#AssistantConnectionSpinner {{
        color: {c['accent']};
        font-size: 15px;
        font-weight: 800;
    }}
    QToolButton#AssistantRetryConnection {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 17px;
        min-width: 34px;
        max-width: 34px;
        min-height: 34px;
        max-height: 34px;
        color: {c['accent']};
        padding: 0;
        font-size: 22px;
        font-weight: 600;
    }}
    QToolButton#AssistantRetryConnection:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QToolButton#AssistantRetryConnection:disabled {{
        color: {c['muted']};
        background: {c['surface']};
    }}
    QFrame#AssistantErrorToast {{
        background: {c['surface']};
        border: 1px solid {c['danger']};
        border-radius: 12px;
    }}
    QLabel#AssistantErrorToastMark {{
        background: {c['danger']};
        color: white;
        border-radius: 11px;
        font-size: 13px;
        font-weight: 800;
    }}
    QLabel#AssistantErrorToastText {{
        color: {c['text']};
        font-size: 12px;
        font-weight: 550;
    }}
    QToolButton#AssistantToastClose {{
        background: transparent;
        border: 0;
        border-radius: 7px;
        color: {c['muted']};
        padding: 0;
        font-size: 19px;
        font-weight: 650;
    }}
    QToolButton#AssistantToastClose:hover {{
        background: {c['surface_hover']};
        color: {c['text']};
    }}
    QWidget#AssistantComposerInputRow, QWidget#AssistantComposerToolbar {{
        background: transparent;
        border: 0;
    }}
    QPushButton#AssistantModelConnectButton {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 9px;
        padding: 7px 14px;
        font-weight: 700;
    }}
    QPushButton#AssistantModelConnectButton:hover {{
        background: {c['primary_hover']};
    }}
    QPushButton#AssistantModelConnectButton:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
    }}
    QComboBox#AssistantProviderSelect, QComboBox#AssistantModelSelect {{
        min-height: 36px;
        padding: 5px 10px;
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        color: {c['text']};
        font-size: 11px;
        font-weight: 600;
    }}
    QComboBox#AssistantProviderSelect:hover, QComboBox#AssistantModelSelect:hover {{
        border-color: {c['accent']};
        background: {c['surface_hover']};
    }}
    QComboBox#AssistantProviderSelect::drop-down, QComboBox#AssistantModelSelect::drop-down {{
        border: 0;
        width: 24px;
    }}
    QPushButton#AssistantRefreshModels {{
        min-height: 36px;
        padding: 6px 10px;
        border-radius: 10px;
        font-size: 11px;
    }}
    QLabel#AssistantComposerStatus {{
        color: {c['muted']};
        font-size: 11px;
        padding-left: 3px;
    }}
    QLabel#AssistantComposerStatus[state="error"] {{
        color: {c['danger']};
    }}
    QPushButton#AssistantStopButton {{
        background: {c['danger']};
        color: white;
        border: 0;
        border-radius: 11px;
        min-width: 38px;
        min-height: 38px;
        padding: 0 12px;
        font-weight: 650;
    }}
    QPushButton#AssistantSendButton {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 21px;
        min-width: 42px;
        max-width: 42px;
        min-height: 42px;
        max-height: 42px;
        padding: 0;
    }}
    QPushButton#AssistantSendButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#AssistantSendButton:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
    }}
    QPushButton#AssistantSendButton:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
    }}
    QPushButton#AssistantVoiceButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 21px;
        min-width: 42px;
        max-width: 42px;
        min-height: 42px;
        max-height: 42px;
        padding: 0;
    }}
    QPushButton#AssistantVoiceButton[active="true"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QPushButton#AssistantVoiceButton[iconOnly="true"] {{
        border-radius: 21px;
        padding: 0;
    }}
    QListWidget#AssistantSettingsNav {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 7px;
        outline: none;
    }}
    QListWidget#AssistantSettingsNav::item {{
        color: {c['muted']};
        background: transparent;
        border-radius: 8px;
        padding: 11px 12px;
        margin: 2px 0;
        font-size: 12px;
        font-weight: 600;
    }}
    QListWidget#AssistantSettingsNav::item:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QListWidget#AssistantSettingsNav::item:selected {{
        color: {c['text']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
    }}
    QStackedWidget#AssistantSettingsSectionStack {{
        background: transparent;
        border: 0;
    }}
    QCheckBox#AssistantAgentMode {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 650;
    }}
    QTextBrowser#AssistantChat {{
        background: {c['window']};
        border: 1px solid {c['border']};
        border-radius: 15px;
        padding: 8px;
        selection-background-color: {c['accent']};
    }}
    QPlainTextEdit#AssistantPrompt {{
        background: transparent;
        border: 0;
        padding: 4px;
    }}
    QPlainTextEdit#AssistantPrompt:focus {{ border: 0; }}
    QPushButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: {RADII['md']}px;
        padding: 7px 12px;
        min-height: 18px;
    }}
    QPushButton:hover {{ border-color: {c['border_hover']}; background: {c['surface_hover']}; }}
    QPushButton:pressed {{ background: {c['surface_hover']}; }}
    QPushButton:focus {{ border: 2px solid {c['focus']}; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; border-color: {c['border']}; }}
    QPushButton#Primary {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{ background: {c['primary_hover']}; }}
    QPushButton#CommandPaletteButton {{
        background: {c['surface_2']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 8px 13px;
        min-height: 18px;
        font-weight: 650;
    }}
    QPushButton#CommandPaletteButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QPushButton#HomePrimaryAction {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 1px solid {c['primary']};
        border-radius: 11px;
        padding: 0 16px;
        min-height: 42px;
        font-weight: 700;
    }}
    QPushButton#HomePrimaryAction:hover {{
        background: {c['primary_hover']};
        border-color: {c['primary_hover']};
    }}
    QPushButton#HomePrimaryAction:pressed {{
        background: {c['primary_hover']};
    }}
    QPushButton#HomePrimaryAction:focus {{
        border-color: {c['accent']};
    }}
    QPushButton#HomeSecondaryAction {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        padding: 0 15px;
        min-height: 42px;
        font-weight: 650;
    }}
    QPushButton#HomeSecondaryAction:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QPushButton#HomeSecondaryAction:pressed {{
        background: {c['surface_2']};
    }}
    QPushButton#HomeSecondaryAction:focus {{
        border-color: {c['accent']};
    }}
    QPushButton#Danger {{ background: {c['danger']}; color: white; border: 0; }}
    QPushButton#Subtle {{ background: transparent; border: 1px solid {c['border']}; }}
    QPushButton#Subtle:hover {{ background: {c['surface_hover']}; }}
    QPushButton#Suggestion {{
        min-height: 14px;
        padding: 6px 8px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 600;
        background: {c['surface_2']};
    }}
    QPushButton#Disclosure {{
        background: transparent;
        border: 0;
        text-align: left;
        color: {c['muted']};
        padding: 6px 2px;
        font-weight: 600;
    }}
    QPushButton#QuickAction {{
        text-align: left;
        padding: 11px 13px;
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        font-weight: 600;
    }}
    QPushButton#Nav {{
        text-align: left;
        padding: 8px 12px;
        border: 1px solid transparent;
        border-left: 0;
        border-radius: 9px;
        background: transparent;
        color: {c['muted']};
        font-weight: 550;
    }}
    QPushButton#Nav:checked {{
        background: {c['accent_soft']};
        border-color: {c['accent_soft']};
        border-left-color: transparent;
        color: {c['accent']};
        font-weight: 600;
    }}
    QPushButton#Nav:hover {{
        background: {c['surface_hover']};
        color: {c['text']};
    }}
    QPushButton#SidebarCollapseButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 7px 10px;
        color: {c['muted']};
        text-align: left;
        font-size: 11px;
        font-weight: 650;
    }}
    QPushButton#SidebarCollapseButton:hover {{
        color: {c['text']};
        border-color: {c['accent']};
        background: {c['surface_hover']};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: {RADII['md']}px;
        padding: 8px 10px;
        selection-background-color: {c['accent']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {c['focus']};
    }}
    QComboBox::drop-down {{ border: 0; width: 27px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        selection-background-color: {c['surface_hover']};
        outline: 0;
        padding: 4px;
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c['border']};
        border-radius: 5px;
        background: {c['input']};
    }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
    QCheckBox::indicator:hover {{ border-color: {c['focus']}; }}
    QRadioButton {{ spacing: 8px; }}
    QProgressBar {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 5px;
        height: 9px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
    QSlider::groove:horizontal {{ height: 5px; background: {c['surface_2']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: {c['accent']}; }}
    QListWidget, QTreeWidget {{
        background: transparent;
        border: 0;
        outline: 0;
        padding: 3px;
    }}
    QListWidget::item, QTreeWidget::item {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADII['md']}px;
        padding: 8px 10px;
        margin: 1px 0;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {c['surface_hover']}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {c['surface_hover']};
        border-color: {c['border_hover']};
        color: {c['text']};
    }}
    QStatusBar {{
        background: {c['surface']};
        color: {c['muted']};
        border-top: 1px solid {c['border']};
        padding: 2px 8px;
    }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 3px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {c['border']};
        border-radius: 4px;
        min-height: 34px;
        min-width: 34px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; height: 0; border: 0; background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 11px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 9px 15px;
        margin-right: 4px;
        border: 0;
        border-bottom: 2px solid transparent;
        color: {c['muted']};
    }}
    QTabBar::tab:selected {{
        color: {c['text']};
        border-bottom-color: {c['accent']};
        font-weight: 700;
    }}
    QDockWidget {{ font-weight: 650; }}
    /* Inspector uses an explicit LTR splitter: drag its handle left to widen. */
    QSplitter#WorkspaceSplitter::handle:horizontal {{
        background: {c['border']};
        width: 6px;
    }}
    QSplitter#WorkspaceSplitter::handle:horizontal:hover {{
        background: {c['accent']};
    }}
    QMainWindow::separator {{
        background: {c['border']};
        width: 6px;
        height: 5px;
    }}
    QMainWindow::separator:hover {{
        background: {c['accent']};
    }}
    QDockWidget::title {{
        background: {c['surface']};
        padding: 9px 13px;
        border-bottom: 1px solid {c['border']};
    }}
    QTableWidget {{
        gridline-color: {c['border']};
        alternate-background-color: {c['surface']};
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        selection-background-color: {c['surface_hover']};
    }}
    QTableWidget::item {{
        padding: 7px 8px;
        border: 0;
        border-bottom: 1px solid {c['border']};
    }}
    QTableWidget::item:selected {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QHeaderView::section {{
        background: {c['surface_2']};
        color: {c['muted']};
        border: 0;
        border-bottom: 1px solid {c['border']};
        padding: 9px;
        font-weight: 650;
    }}
    QMenu {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 5px;
    }}
    QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c['surface_hover']}; }}
    /* Modular AI workspace */
    QFrame#AssistantSidebar {{
        background: {c['surface']};
        border-right: 1px solid {c['border']};
    }}
    QLabel#AssistantBrandIcon {{
        background: transparent;
        border: 0;
        padding: 0;
        margin: 0;
    }}
    QPushButton#AssistantIconButton {{
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 0;
        min-width: 28px;
        max-width: 30px;
        min-height: 28px;
        max-height: 30px;
        font-size: 17px;
    }}
    QLineEdit#AssistantHistorySearch {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 9px 10px;
    }}
    QListWidget#AssistantSessionList {{
        background: transparent;
        border: 0;
        padding: 0;
    }}
    QListWidget#AssistantSessionList::item {{
        background: transparent;
        border: 0;
        border-radius: 8px;
        padding: 9px 10px;
        margin: 1px 0;
        color: {c['text']};
    }}
    QListWidget#AssistantSessionList::item:hover {{
        background: {c['surface_hover']};
    }}
    QListWidget#AssistantSessionList::item:selected {{
        background: {c['surface_2']};
        color: {c['text']};
        border: 1px solid {c['border']};
    }}
    QWidget#AssistantSessionRow {{
        background: transparent;
        border: 0;
    }}
    QLabel#AssistantSessionTitle {{
        color: {c['text']};
        background: transparent;
        font-size: 11px;
        font-weight: 650;
    }}
    QLabel#AssistantSessionPreview {{
        color: {c['muted']};
        background: transparent;
        font-size: 10px;
        font-weight: 400;
    }}
    QLabel#AssistantSidebarEmpty {{
        color: {c['muted']};
        padding: 18px;
    }}
    QFrame#AssistantSidebarFooter {{
        border-top: 1px solid {c['border']};
    }}
    QPushButton#AssistantSidebarAction {{
        text-align: left;
        background: transparent;
        border: 0;
        border-radius: 8px;
        padding: 8px 9px;
    }}
    QPushButton#AssistantSidebarAction:hover {{
        background: {c['surface_hover']};
    }}
    QPushButton#AssistantSidebarAction[collapsed="true"] {{
        text-align: center;
        padding: 0;
        min-width: 38px;
        max-width: 38px;
        min-height: 38px;
        max-height: 38px;
        border-radius: 10px;
    }}
    QWidget#AssistantSidebarFooterSpacer {{
        background: transparent;
        border: 0;
    }}
    QWidget#AssistantMessageRow {{
        background: transparent;
        border: 0;
    }}
    QFrame#AssistantConversationHeader {{
        background: {c['window']};
        border-bottom: 1px solid {c['border']};
    }}
    QLabel#AssistantWorkspaceBadge {{
        color: {c['muted']};
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 6px 9px;
        max-width: 390px;
    }}
    QFrame#AssistantConversationView {{
        background: {c['window']};
        border: 0;
    }}
    QScrollArea#AssistantConversationScroll {{
        background: {c['window']};
        border: 0;
    }}
    QWidget#AssistantConversationContent {{
        background: {c['window']};
    }}
    QLabel#AssistantEmptyTitle {{
        font-size: 27px;
        font-weight: 720;
        color: {c['text']};
    }}
    QLabel#AssistantEmptyDescription {{
        color: {c['muted']};
        font-size: 13px;
    }}
    QFrame#AssistantEmptyState {{
        background: transparent;
        border: 0;
    }}
    QPushButton#AssistantPromptSuggestion {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 11px 14px;
        min-width: 0;
        min-height: 68px;
        text-align: left;
    }}
    QPushButton#AssistantPromptSuggestion:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QPushButton#AssistantPromptSuggestion:pressed {{
        background: {c['surface_2']};
    }}
    QLabel#AssistantPromptSuggestionTitle {{
        color: {c['text']};
        background: transparent;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#AssistantPromptSuggestionDescription {{
        color: {c['muted']};
        background: transparent;
        font-size: 11px;
        font-weight: 400;
    }}
    QPushButton#AssistantPromptSuggestion[compact="true"] {{
        padding: 9px 10px;
        min-height: 42px;
        font-size: 11px;
    }}
    QFrame#AssistantMessage_user {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 14px;
    }}
    QFrame#AssistantMessage_assistant {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 14px;
    }}
    QFrame#AssistantMessage_tool {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QFrame#AssistantMessage_error {{
        background: {c['danger']};
        border: 0;
        border-radius: 10px;
    }}
    QFrame#AssistantMessage_system {{
        background: transparent;
        border: 0;
    }}
    QLabel#AssistantMessageRole {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 750;
    }}
    QToolButton#AssistantMessageDisclosure {{
        color: {c['muted']};
        background: transparent;
        border: 0;
        border-radius: 5px;
        padding: 2px 5px;
        font-size: 10px;
        font-weight: 600;
    }}
    QToolButton#AssistantMessageDisclosure:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QTextBrowser#AssistantMessageBody {{
        color: {c['text']};
        background: transparent;
        border: 0;
        padding: 1px 2px;
        selection-background-color: {c['accent']};
    }}
    QToolButton#AssistantMessageAction {{
        background: transparent;
        border: 0;
        border-radius: 6px;
        color: {c['muted']};
        padding: 4px 7px;
    }}
    QToolButton#AssistantMessageAction:hover {{
        background: {c['surface_hover']};
        color: {c['text']};
    }}
    QToolButton#AssistantMessageAction[copied="true"] {{
        color: {c['success']};
    }}
    QFrame#AssistantActivity {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QFrame#AssistantThinking {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 11px;
    }}
    QToolButton#AssistantThinkingToggle {{
        color: {c['text']};
        background: transparent;
        border: 0;
        border-radius: 6px;
        padding: 3px 5px;
        font-size: 11px;
        font-weight: 700;
    }}
    QToolButton#AssistantThinkingToggle:disabled {{
        color: {c['text']};
    }}
    QToolButton#AssistantThinkingToggle:hover {{
        background: {c['surface_hover']};
    }}
    QLabel#AssistantThinkingStatus {{
        color: {c['muted']};
        font-size: 10px;
    }}
    QPlainTextEdit#AssistantThinkingBody {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 7px;
        font-size: 11px;
        selection-background-color: {c['accent']};
    }}
    QFrame#AssistantInlineThinking {{
        background: transparent;
        border: 0;
        border-radius: 7px;
    }}
    QToolButton#AssistantInlineThinkingToggle {{
        color: {c['muted']};
        background: transparent;
        border: 0;
        border-radius: 6px;
        padding: 2px 4px;
        font-size: 11px;
        font-weight: 650;
    }}
    QToolButton#AssistantInlineThinkingToggle:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QLabel#AssistantInlineThinkingStatus {{
        color: {c['muted']};
        font-size: 10px;
    }}
    QPlainTextEdit#AssistantInlineThinkingBody {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 6px 8px;
        font-size: 11px;
        selection-background-color: {c['accent']};
    }}
    QLabel#AssistantActivityDetail {{
        color: {c['muted']};
        font-size: 11px;
        padding-left: 22px;
    }}
    QToolButton#AssistantActivityToggle {{
        background: transparent;
        border: 0;
        font-weight: 650;
    }}
    QFrame#AssistantActivityRow[state="running"] QLabel#AssistantActivityIcon {{
        color: {c['warning']};
    }}
    QFrame#AssistantActivityRow[state="completed"] QLabel#AssistantActivityIcon {{
        color: {c['success']};
    }}
    QFrame#AssistantActivityRow[state="failed"] QLabel#AssistantActivityIcon {{
        color: {c['danger']};
    }}
    QPushButton#AssistantJumpLatest {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 16px;
        padding: 7px 13px;
    }}
        QToolTip {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: 6px 8px;
    }}

    /* New Transcription workspace */
    QWidget#NewTranscriptionPage, QWidget#NewTranscriptionContent,
    QWidget#SubtitleStudioPage, QWidget#SubtitleStudioContent {{
        background: transparent;
    }}
    QScrollArea#NewTranscriptionScroll, QScrollArea#SubtitleStudioScroll {{
        background: transparent;
        border: 0;
    }}
    QLabel#TranscriptionSectionTitle {{
        color: {c['text']};
        font-size: 14px;
        font-weight: 750;
    }}
    QLabel#TranscriptionSectionHint {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLabel#TranscriptionFieldLabel {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 700;
        padding-left: 1px;
    }}
    QPushButton#TranscriptionChooseMedia {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 10px;
        padding: 9px 16px;
        font-weight: 750;
    }}
    QPushButton#TranscriptionChooseMedia:hover {{ background: {c['primary_hover']}; }}
    QLabel#TranscriptionFileName {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px dashed {c['border']};
        border-radius: 10px;
        padding: 8px 12px;
        font-size: 12px;
    }}
    QPushButton#TranscriptionCloseMedia {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        color: {c['muted']};
        font-size: 19px;
        padding: 0;
    }}
    QPushButton#TranscriptionCloseMedia:hover {{
        color: {c['danger']};
        border-color: {c['danger']};
    }}
    QPushButton#TranscriptionDefaultModel, QPushButton#TranscriptionToolButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 8px 11px;
        font-size: 11px;
        font-weight: 650;
    }}
    QPushButton#TranscriptionDefaultModel:hover, QPushButton#TranscriptionToolButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QLabel#TranscriptionPrivacyHint {{
        color: {c['muted']};
        font-size: 11px;
        padding: 3px 0;
    }}
    QLabel#TranscriptionPrivacyMark {{
        color: {c['accent']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        font-size: 12px;
        font-weight: 800;
    }}
    QLabel#TranscriptionPlayerStatus {{
        color: {c['muted']};
        font-size: 10px;
    }}
    QPushButton#TranscriptionPlayButton {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 21px;
        font-size: 16px;
        font-weight: 750;
        padding: 0;
    }}
    QPushButton#TranscriptionPlayButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#TranscriptionPlayButton:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
    }}
    QLabel#TranscriptionPlaybackTime {{
        color: {c['text']};
        font-size: 11px;
        font-weight: 700;
        font-family: 'Consolas', 'Cascadia Code', monospace;
    }}
    QLabel#TranscriptionWordCount {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 650;
    }}
    QLineEdit#TranscriptionSearch, QLineEdit#TranscriptionReplace {{
        min-height: 20px;
    }}
    QPlainTextEdit#TranscriptionEditor {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        padding: 14px;
        selection-background-color: {c['accent']};
        font-size: 13px;
    }}
    QPlainTextEdit#TranscriptionEditor:focus {{ border-color: {c['focus']}; }}
    QPushButton#TranscriptionExportSubtitles {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 9px;
        padding: 9px 14px;
        font-weight: 700;
    }}
    QPushButton#TranscriptionExportSubtitles:hover {{ background: {c['primary_hover']}; }}
    QFrame#TranscriptionActionBar {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 13px;
    }}
    QLabel#TranscriptionProgressLabel {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 650;
        min-width: 80px;
    }}
    QProgressBar#TranscriptionProgress {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 5px;
        min-height: 8px;
        max-height: 8px;
    }}
    QProgressBar#TranscriptionProgress::chunk {{
        background: {c['accent']};
        border-radius: 4px;
    }}
    QPushButton#TranscriptionCancel {{
        color: {c['danger']};
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 9px;
        font-weight: 650;
    }}
    QPushButton#TranscriptionStart {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 10px;
        padding: 9px 17px;
        font-weight: 750;
    }}
    QPushButton#TranscriptionStart:hover {{ background: {c['primary_hover']}; }}
    QPushButton#TranscriptionStart:disabled {{
        background: {c['surface_2']};
        color: {c['muted']};
    }}

    /* Subtitle Studio: metrics, timing tools and cue editing surface */
    QFrame#SubtitleMetricCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#SubtitleMetricCaption {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.9px;
    }}
    QLabel#SubtitleMetricValue {{
        color: {c['text']};
        font-size: 21px;
        font-weight: 750;
    }}
    QPushButton#SubtitleToolButton {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 8px 12px;
        font-size: 11px;
        font-weight: 650;
    }}
    QPushButton#SubtitleToolButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QPushButton#SubtitleDeleteButton {{
        color: {c['danger']};
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 8px 12px;
        font-size: 11px;
        font-weight: 650;
    }}
    QPushButton#SubtitleDeleteButton:hover {{
        border-color: {c['danger']};
        background: {c['surface_hover']};
    }}
    QPushButton#SubtitleExportButton {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 9px;
        padding: 8px 14px;
        font-weight: 750;
    }}
    QPushButton#SubtitleExportButton:hover {{ background: {c['primary_hover']}; }}
    QFrame#SubtitleTimingTool {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 11px;
    }}
    QLabel#SubtitleTimingTitle {{
        color: {c['text']};
        font-size: 12px;
        font-weight: 750;
    }}
    QLabel#SubtitleTimingDescription {{
        color: {c['muted']};
        font-size: 10px;
    }}
    QPushButton#SubtitleTimingApply {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 7px 11px;
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#SubtitleTimingApply:hover {{
        border-color: {c['accent']};
        background: {c['surface_hover']};
    }}
    QTableWidget#SubtitleCueTable {{
        gridline-color: transparent;
        alternate-background-color: {c['surface_2']};
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 11px;
        selection-background-color: {c['surface_hover']};
        outline: 0;
    }}
    QTableWidget#SubtitleCueTable::item {{
        padding: 9px 10px;
        border: 0;
        border-bottom: 1px solid {c['border']};
    }}
    QTableWidget#SubtitleCueTable::item:selected {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QTableWidget#SubtitleCueTable QLineEdit {{
        padding: 5px 7px;
        border-radius: 6px;
    }}
    QLabel#SubtitleEmptyState {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px dashed {c['border']};
        border-radius: 11px;
        padding: 22px;
        font-size: 12px;
        font-weight: 550;
    }}
    QFrame#SubtitleReportCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 11px;
    }}
    QLabel#SubtitleReportMark {{
        color: {c['success']};
        background: {c['surface_2']};
        border-radius: 13px;
        font-size: 13px;
        font-weight: 800;
    }}
    QLabel#SubtitleReportMark[state="warning"] {{ color: {c['warning']}; }}
    QLabel#SubtitleReportMark[state="success"] {{ color: {c['success']}; }}
    QLabel#SubtitleValidationReport {{
        color: {c['muted']};
        font-size: 11px;
        padding: 1px 0;
    }}
    QLabel#SubtitleValidationReport[state="success"] {{ color: {c['success']}; }}
    QLabel#SubtitleValidationReport[state="warning"] {{ color: {c['warning']}; }}

    QFrame#RecordingOptionsCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#RecordingDeviceTitle {{
        color: {c['text']};
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#RecordingDeviceHint {{
        color: {c['muted']};
        font-size: 10px;
        padding-left: 2px;
    }}
    QComboBox#RecordingMicrophoneCombo {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        min-height: 18px;
        padding: 5px 9px;
        font-size: 11px;
    }}
    QComboBox#RecordingMicrophoneCombo:hover {{
        border-color: {c['accent']};
    }}
    QPushButton#RecordingRefreshDevices {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 0;
        font-size: 17px;
    }}
    QPushButton#RecordingRefreshDevices:hover {{
        background: {c['surface_hover']};
        border-color: {c['accent']};
    }}
    QCheckBox#RecordingAutoTranscribe {{
        color: {c['text']};
        font-size: 11px;
        font-weight: 600;
        spacing: 8px;
    }}
    QLabel#RecordingLocalNote {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 750;
        letter-spacing: 0.5px;
    }}
    /* New Transcription: compact source rail and a single, editor-led workspace */
    QFrame#TranscriptionSourceBar {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {c['border']};
        border-radius: 0;
    }}
    QLabel#TranscriptionSourceLabel {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 1px;
        padding-right: 3px;
    }}
    QLabel#TranscriptionFileName {{
        color: {c['text']};
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 4px 7px;
        font-size: 12px;
    }}
    QPushButton#TranscriptionChooseMedia {{
        min-width: 112px;
        padding: 6px 12px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#TranscriptionCloseMedia {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 0;
    }}
    QPushButton#TranscriptionCloseMedia:hover {{
        background: {c['surface_hover']};
        border-color: {c['border']};
    }}
    QFrame#TranscriptionSettingsPanel {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 11px;
    }}
    QLabel#TranscriptionSettingsTitle {{
        color: {c['text']};
        font-size: 12px;
        font-weight: 750;
    }}
    QLabel#TranscriptionInlineLabel {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.5px;
    }}
    QFrame#TranscriptionSettingsPanel QComboBox,
    QFrame#TranscriptionSettingsPanel QSpinBox {{
        min-height: 20px;
        padding-top: 5px;
        padding-bottom: 5px;
        border-radius: 7px;
        font-size: 11px;
    }}
    QFrame#TranscriptionSettingsPanel QCheckBox {{
        font-size: 10px;
        spacing: 6px;
    }}
    QLineEdit#TranscriptionSearch, QLineEdit#TranscriptionReplace,
    QFrame#TranscriptionSettingsPanel QLineEdit {{
        min-height: 18px;
        padding: 6px 9px;
        border-radius: 8px;
        font-size: 11px;
    }}
    QPushButton#TranscriptionDefaultModel {{
        min-width: 58px;
        padding: 5px 8px;
        border-radius: 7px;
        font-size: 10px;
    }}
    QLabel#TranscriptionPrivacyMark {{
        min-width: 16px;
        max-width: 16px;
        min-height: 16px;
        max-height: 16px;
        border-radius: 8px;
        font-size: 10px;
    }}
    QLabel#TranscriptionPrivacyHint {{
        font-size: 10px;
        padding: 0;
    }}
    QFrame#TranscriptionWorkspace {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 13px;
    }}
    QFrame#TranscriptionPlayerBar {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 9px;
    }}
    QLabel#TranscriptionPlayerStatus {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 700;
    }}
    QPushButton#TranscriptionPlayButton {{
        background: {c['primary']};
        color: {c['on_primary']};
        border: 0;
        border-radius: 18px;
        padding: 0;
    }}
    QPushButton#TranscriptionPlayButton:hover {{ background: {c['primary_hover']}; }}
    QPushButton#TranscriptionPlayButton:disabled {{
        background: {c['surface_hover']};
        color: {c['muted']};
    }}
    QLabel#TranscriptionPlaybackTime {{
        color: {c['text']};
        font-size: 10px;
        font-weight: 750;
        font-family: 'Consolas', 'Cascadia Code', monospace;
    }}
    QSlider#TranscriptionSeekSlider::groove:horizontal {{
        height: 5px;
        background: {c['border']};
        border-radius: 3px;
    }}
    QSlider#TranscriptionSeekSlider::sub-page:horizontal {{
        background: {c['accent']};
        border-radius: 3px;
    }}
    QSlider#TranscriptionSeekSlider::handle:horizontal {{
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border: 2px solid {c['surface_2']};
        border-radius: 7px;
        background: {c['accent']};
    }}
    QComboBox#TranscriptionSpeedCombo {{
        min-height: 18px;
    }}
    QSlider#TranscriptionVolumeSlider::groove:horizontal {{
        height: 4px;
        background: {c['border']};
        border-radius: 2px;
    }}
    QSlider#TranscriptionVolumeSlider::sub-page:horizontal {{
        background: {c['accent']};
        border-radius: 2px;
    }}
    QSlider#TranscriptionVolumeSlider::handle:horizontal {{
        width: 10px;
        height: 10px;
        margin: -3px 0;
        border: 1px solid {c['surface']};
        border-radius: 5px;
        background: {c['accent']};
    }}
    QLabel#TranscriptionSectionTitle {{
        font-size: 15px;
        font-weight: 750;
    }}
    QLabel#TranscriptionWordCount {{
        color: {c['muted']};
        background: {c['surface_2']};
        border-radius: 7px;
        padding: 5px 8px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLineEdit#TranscriptionSearch, QLineEdit#TranscriptionReplace {{
        min-height: 18px;
        padding: 6px 10px;
        border-radius: 8px;
    }}
    QPushButton#TranscriptionToolButton {{
        min-height: 18px;
        padding: 6px 10px;
        border-radius: 8px;
        font-size: 10px;
        font-weight: 700;
    }}
    QPlainTextEdit#TranscriptionEditor {{
        background: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 18px 19px;
        selection-background-color: {c['accent']};
        font-size: 14px;
    }}
    QPlainTextEdit#TranscriptionEditor:focus {{
        border-color: {c['focus']};
    }}
    QFrame#TranscriptionActionBar {{
        background: transparent;
        border: 0;
        border-top: 1px solid {c['border']};
        border-radius: 0;
    }}
    QLabel#TranscriptionProgressLabel {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 650;
        min-width: 0;
    }}
    QProgressBar#TranscriptionProgress {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 2px;
        min-height: 4px;
        max-height: 4px;
    }}
    QProgressBar#TranscriptionProgress::chunk {{
        background: {c['accent']};
        border-radius: 2px;
    }}
    QPushButton#TranscriptionCancel {{
        min-height: 18px;
        padding: 7px 13px;
        border-radius: 8px;
        font-size: 10px;
    }}
    QPushButton#TranscriptionStart {{
        min-height: 20px;
        padding: 8px 16px;
        border-radius: 9px;
        font-size: 11px;
        font-weight: 750;
    }}

    /* Shared workspace chrome and dock controls */
    QLabel#InspectorTitle {{
        color: {c['text']};
        font-size: 15px;
        font-weight: 650;
    }}
    QLabel#DrawerTitle {{
        color: {c['text']};
        font-size: 13px;
        font-weight: 650;
    }}
    QLabel#DrawerTitleIcon {{
        color: {c['muted']};
        font-size: 16px;
        font-weight: 650;
    }}
    QPushButton#DrawerToggleButton {{
        color: {c['muted']};
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 2px 8px;
        min-height: 0;
        max-height: 25px;
        font-size: 10px;
        font-weight: 600;
    }}
    QPushButton#DrawerToggleButton:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
        border-color: {c['border_hover']};
    }}
    QPushButton#DrawerToggleButton:checked {{
        color: {c['text']};
        background: {c['surface_2']};
        border-color: {c['border_hover']};
    }}
    QPushButton#DrawerCloseButton {{
        color: {c['muted']};
        background: transparent;
        border: 0;
        border-radius: 7px;
        font-size: 20px;
        font-weight: 400;
        padding: 0;
    }}
    QPushButton#DrawerCloseButton:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}

    /* Model Library semantic labels */
    QLabel#ModelDetailHeading, QLabel#ModelInstalledSummary {{
        color: {c['text']};
        font-size: 15px;
        font-weight: 650;
    }}
    QLabel#ModelCompatibility {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 4px 8px;
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#ModelCompatibility[state="compatible"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#ModelCompatibility[state="incompatible"] {{
        color: {c['danger']};
        border-color: {c['danger']};
    }}
    QLabel#ModelCompatibility[state="warning"] {{
        color: {c['warning']};
        border-color: {c['warning']};
    }}
    QListWidget#DownloadTaskList {{
        background: transparent;
        border: 0;
        outline: 0;
    }}
    QListWidget#DownloadTaskList::item {{
        background: transparent;
        border: 0;
        padding: 0;
    }}

    /* Settings, recording and audio-library typography */
    QLabel#SettingsSectionTitle {{
        color: {c['text']};
        font-size: 16px;
        font-weight: 650;
        padding: 2px 0;
    }}
    QLabel#SettingsSubsectionTitle {{
        color: {c['text']};
        font-weight: 650;
        margin-top: 8px;
    }}
    QLabel#RecordingFormatBadge {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.7px;
    }}
    QLabel#AudioLibraryListHeading {{
        color: {c['muted']};
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1px;
    }}


    /* Model Library cards: neutral surfaces; status appears in compact labels and progress */
    QFrame#DownloadTaskCard, QFrame#InstalledModelCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#ModelTaskTitle, QLabel#ModelInstalledTitle {{
        color: {c['text']};
        font-size: 13px;
        font-weight: 650;
    }}
    QLabel#ModelRuntimeBadge {{
        color: {c['accent']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 4px 7px;
        font-size: 9px;
        font-weight: 700;
    }}
    QLabel#ModelTaskStateBadge, QLabel#ModelInstalledStateBadge {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 4px 8px;
        font-size: 9px;
        font-weight: 750;
    }}
    QLabel#ModelTaskStateBadge[state="success"],
    QLabel#ModelInstalledStateBadge[state="active"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#ModelTaskStateBadge[state="danger"] {{
        color: {c['danger']};
        border-color: {c['danger']};
    }}
    QLabel#ModelTaskStateBadge[state="warning"],
    QLabel#ModelInstalledStateBadge[state="repair"] {{
        color: {c['warning']};
        border-color: {c['warning']};
    }}
    QLabel#ModelTaskStateBadge[state="info"],
    QLabel#ModelInstalledStateBadge[state="ready"] {{
        color: {c['accent']};
        border-color: {c['accent']};
    }}
    QLabel#ModelTaskMeta, QLabel#ModelRevision {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLabel#ModelRevision {{
        font-size: 10px;
    }}
    QLabel#ModelTransferCaption, QLabel#ModelPathCaption {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.7px;
    }}
    QLabel#ModelTransferValue {{
        color: {c['text']};
        font-size: 11px;
        font-weight: 650;
    }}
    QProgressBar#DownloadTaskProgress {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 4px;
        min-height: 7px;
        max-height: 7px;
    }}
    QProgressBar#DownloadTaskProgress::chunk {{
        background: {c['accent']};
        border-radius: 4px;
    }}
    QProgressBar#DownloadTaskProgress[state="success"]::chunk {{
        background: {c['success']};
    }}
    QProgressBar#DownloadTaskProgress[state="danger"]::chunk {{
        background: {c['danger']};
    }}
    QProgressBar#DownloadTaskProgress[state="warning"]::chunk {{
        background: {c['warning']};
    }}
    QLabel#ModelErrorNotice {{
        color: {c['danger']};
        background: {c['surface_2']};
        border: 1px solid {c['danger']};
        border-radius: 7px;
        padding: 7px 9px;
        font-size: 11px;
    }}
    QLabel#ModelPendingAction {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QPushButton#ModelTaskActionButton, QPushButton#ModelInstalledActionButton {{
        color: {c['text']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#ModelTaskActionButton:hover,
    QPushButton#ModelInstalledActionButton:hover {{
        background: {c['surface_hover']};
        border-color: {c['border_hover']};
    }}
    QPushButton#ModelTaskActionButton[variant="primary"],
    QPushButton#ModelInstalledActionButton[variant="primary"] {{
        color: {c['on_primary']};
        background: {c['primary']};
        border-color: {c['primary']};
    }}
    QPushButton#ModelTaskActionButton[variant="primary"]:hover,
    QPushButton#ModelInstalledActionButton[variant="primary"]:hover {{
        background: {c['primary_hover']};
        border-color: {c['primary_hover']};
    }}
    QPushButton#ModelTaskActionButton[variant="danger"],
    QPushButton#ModelInstalledActionButton[variant="danger"] {{
        color: {c['danger']};
        background: {c['surface']};
        border-color: {c['border']};
    }}
    QPushButton#ModelTaskActionButton[variant="danger"]:hover,
    QPushButton#ModelInstalledActionButton[variant="danger"]:hover {{
        background: {c['surface_hover']};
        border-color: {c['danger']};
    }}
    QPushButton#ModelTaskActionButton[variant="warning"] {{
        color: {c['warning']};
        background: {c['surface']};
        border-color: {c['border']};
    }}
    QPushButton#ModelTaskActionButton[variant="warning"]:hover {{
        background: {c['surface_hover']};
        border-color: {c['warning']};
    }}
    QFrame#ModelInstalledInfoPanel {{
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
    }}
    QLabel#ModelInstalledInfoLabel {{
        color: {c['text']};
        border: 0;
        background: transparent;
        font-size: 11px;
    }}
    QLabel#ModelDefaultBadge {{
        color: {c['accent']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 9px;
        font-weight: 700;
    }}
    QLabel#ModelPathLabel {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 7px 8px;
        font-size: 10px;
    }}
    QLabel#ModelInstalledCompatibility {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 10px;
    }}
    QLabel#ModelInstalledCompatibility[state="compatible"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#ModelInstalledCompatibility[state="warning"] {{
        color: {c['warning']};
        border-color: {c['warning']};
    }}


    /* Reusable workspace composition primitives */
    QWidget#SectionHeader, QWidget#SectionHeaderCopy {{
        background: transparent;
    }}
    QLabel#SectionDescription {{
        color: {c['muted']};
        font-size: 12px;
    }}
    QFrame#WorkspaceEmptyState {{
        background: {c['surface']};
        border: 1px dashed {c['border']};
        border-radius: 12px;
    }}
    QLabel#EmptyStateTitle {{
        color: {c['text']};
        font-size: 15px;
        font-weight: 650;
    }}
    QLabel#EmptyStateDescription {{
        color: {c['muted']};
        font-size: 12px;
    }}
    QLabel#StatusPill {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 4px 8px;
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#StatusPill[state="success"] {{
        color: {c['success']};
        border-color: {c['success']};
    }}
    QLabel#StatusPill[state="warning"] {{
        color: {c['warning']};
        border-color: {c['warning']};
    }}
    QLabel#StatusPill[state="danger"] {{
        color: {c['danger']};
        border-color: {c['danger']};
    }}
    QLabel#StatusPill[state="info"] {{
        color: {c['accent']};
        border-color: {c['accent']};
    }}
    QFrame#MetricCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QLabel#MetricCaption {{
        color: {c['muted']};
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.7px;
    }}
    QLabel#MetricValue {{
        color: {c['text']};
        font-size: 22px;
        font-weight: 650;
    }}
    QLabel#MetricDetail {{
        color: {c['muted']};
        font-size: 10px;
    }}
    QFrame#WorkspacePanel {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}


    QWidget#HomePage {{
        background: transparent;
    }}
    QPushButton#WorkspaceShortcut {{
        text-align: left;
        color: {c['text']};
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 8px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#WorkspaceShortcut:hover {{
        background: {c['surface_hover']};
        border-color: {c['border_hover']};
    }}


    QLabel#HistoryDetailTitle {{
        color: {c['text']};
        font-size: 19px;
        font-weight: 650;
    }}
    QLabel#HistoryPreviewHeading {{
        color: {c['text']};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#HistoryPreview {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 12px;
        font-size: 12px;
    }}


    QLabel#CleanupSourceName {{
        color: {c['text']};
        font-size: 13px;
        font-weight: 650;
    }}
    QFrame#CleanupOutputPanel {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#CleanupSafetyNote {{
        color: {c['success']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 11px;
        font-size: 11px;
    }}
    QLabel#CleanupResult {{
        color: {c['muted']};
        background: {c['surface_2']};
        border-radius: 8px;
        padding: 12px;
        font-size: 12px;
    }}
    QPushButton#CleanupRenderButton {{
        min-height: 40px;
        font-weight: 650;
    }}


    QFrame#RecorderConsole {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QFrame#RecordingOptionsCard {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}


    QFrame#BatchStatusPanel {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#BatchSummary {{
        color: {c['text']};
        font-size: 13px;
        font-weight: 600;
    }}
    QLabel#BatchResourceNote {{
        color: {c['muted']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 10px;
        font-size: 11px;
    }}
    QProgressBar#BatchProgress {{
        background: {c['surface_2']};
        border: 0;
        border-radius: 4px;
        min-height: 8px;
        max-height: 8px;
    }}
    QProgressBar#BatchProgress::chunk {{
        background: {c['accent']};
        border-radius: 4px;
    }}
    QListWidget#BatchQueue {{
        background: transparent;
        border: 0;
    }}


    QFrame#SubtitleToolbar {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}


    QFrame#EditorInspector {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}
    QLabel#EditorInspectorTitle {{
        color: {c['text']};
        font-size: 16px;
        font-weight: 650;
    }}
    QLabel#EditorInspectorMeta {{
        color: {c['muted']};
        font-size: 11px;
    }}
    QLabel#EditorSegmentPreview {{
        color: {c['text']};
        background: {c['surface_2']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 12px;
        font-size: 13px;
    }}
    QTableWidget#TranscriptSegmentTable {{
        background: transparent;
        border: 0;
        outline: 0;
        selection-background-color: {c['surface_hover']};
    }}


    QListWidget#SettingsNavigation {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 6px;
    }}
    QListWidget#SettingsNavigation::item {{
        color: {c['muted']};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 9px 10px;
        margin: 1px 0;
        font-size: 12px;
    }}
    QListWidget#SettingsNavigation::item:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
    }}
    QListWidget#SettingsNavigation::item:selected {{
        color: {c['text']};
        background: {c['surface_2']};
        border-color: {c['border_hover']};
        font-weight: 650;
    }}
    QScrollArea#SettingsContentScroll {{
        background: transparent;
        border: 0;
    }}
    QScrollArea#SettingsContentScroll > QWidget > QWidget {{
        background: transparent;
    }}
    QFrame#RecordingListRow {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {c['border']};
        border-radius: 0;
    }}
    QFrame#RecordingListRow:hover {{
        background: {c['surface_hover']};
    }}
    QFrame#RecordingListRow[selected="true"] {{
        background: {c['surface_2']};
    }}


    QFrame#ModelDiscoveryToolbar {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QFrame#ModelDiscoveryToolbar QLabel {{
        color: {c['muted']};
        font-size: 11px;
        font-weight: 650;
    }}


    QToolButton#TranscriptionAdvancedToggle {{
        color: {c['muted']};
        background: transparent;
        border: 0;
        padding: 4px 6px;
        font-size: 11px;
        font-weight: 600;
    }}
    QToolButton#TranscriptionAdvancedToggle:hover {{
        color: {c['text']};
        background: {c['surface_hover']};
        border-radius: 6px;
    }}

    """