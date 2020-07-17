from __future__ import absolute_import

from sentry.models import Integration, Project, GroupStatus
from sentry.utils.compat import filter
from sentry.utils.http import absolute_uri
from .client import MsTeamsClient

MSTEAMS_MAX_ITERS = 100


def channel_filter(channel, name):
    # the general channel has no name in the list
    # retrieved from the REST API call
    if channel.get("name"):
        return name.lower() == channel.get("name").lower()
    else:
        return name.lower() == "general"


def get_channel_id(organization, integration_id, name):
    try:
        integration = Integration.objects.get(
            provider="msteams", organizations=organization, id=integration_id
        )
    except Integration.DoesNotExist:
        return None

    team_id = integration.external_id
    client = MsTeamsClient(integration)

    # handle searching for channels first
    channel_list = client.get_channel_list(team_id)
    filtered_channels = list(filter(lambda x: channel_filter(x, name), channel_list))
    if len(filtered_channels) > 0:
        return filtered_channels[0].get("id")

    # handle searching for users
    members = client.get_member_list(team_id, None)
    for i in range(MSTEAMS_MAX_ITERS):
        member_list = members.get("members")
        continuation_token = members.get("continuationToken")

        filtered_members = list(
            filter(lambda x: x.get("name").lower() == name.lower(), member_list)
        )
        if len(filtered_members) > 0:
            # TODO: handle duplicate username case
            user_id = filtered_members[0].get("id")
            tenant_id = filtered_members[0].get("tenantId")
            return client.get_user_conversation_id(user_id, tenant_id)

        if not continuation_token:
            return None

        members = client.get_member_list(team_id, continuation_token)

    return None


def build_welcome_card(signed_params):
    url = u"%s?signed_params=%s" % (absolute_uri("/extensions/msteams/configure/"), signed_params,)
    # TODO: Refactor message creation
    logo = {
        "type": "Image",
        "url": "https://sentry-brand.storage.googleapis.com/sentry-glyph-black.png",
        "size": "Medium",
    }
    welcome = {
        "type": "TextBlock",
        "weight": "Bolder",
        "size": "Large",
        "text": "Welcome to Sentry for Microsoft Teams",
        "wrap": True,
    }
    description = {
        "type": "TextBlock",
        "text": "You can use the Sentry app for Microsoft Teams to get notifications that allow you to assign, ignore, or resolve directly in your chat.",
        "wrap": True,
    }
    instruction = {
        "type": "TextBlock",
        "text": "If that sounds good to you, finish the setup process.",
        "wrap": True,
    }
    button = {
        "type": "Action.OpenUrl",
        "title": "Complete Setup",
        "url": url,
    }
    return {
        "type": "AdaptiveCard",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "items": [logo], "width": "auto"},
                    {
                        "type": "Column",
                        "items": [welcome],
                        "width": "stretch",
                        "verticalContentAlignment": "Center",
                    },
                ],
            },
            description,
            instruction,
        ],
        "actions": [button],
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
    }


def build_incident_title(group):
    # TODO: implement with event as well
    title = {"type": "TextBlock", "size": "Large", "weight": "Bolder"}
    ev_metadata = group.get_event_metadata()
    ev_type = group.get_event_type()

    if ev_type == "error" and "type" in ev_metadata:
        text = ev_metadata["type"]
    else:
        text = group.title

    link = group.get_absolute_url()

    title_text = u"[{}]({})".format(text, link)
    title["text"] = title_text
    return title


def build_incident_desc(group):
    # TODO: implement with event as well
    ev_type = group.get_event_type()
    if ev_type == "error":
        ev_metadata = group.get_event_metadata()
        text = ev_metadata.get("value") or ev_metadata.get("function")
        return {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": text}
    else:
        return None


def build_rule_url(rule, group, project):
    org_slug = group.organization.slug
    project_slug = project.slug
    rule_url = u"/settings/{}/projects/{}/alerts/rules/{}/".format(org_slug, project_slug, rule.id)
    return absolute_uri(rule_url)


def build_incident_footer(group, rules, project):
    # TODO: implement with event as well
    image_column = {
        "type": "Column",
        "items": [
            {
                "type": "Image",
                "url": "https://sentry-brand.storage.googleapis.com/sentry-glyph-black.png",
                "height": "20px",
            }
        ],
        "width": "auto",
    }

    text = u"{}".format(group.qualified_short_id)
    if rules:
        rule_url = build_rule_url(rules[0], group, project)
        text += u" via [{}]({})".format(rules[0].label, rule_url)
        if len(rules) > 1:
            text += u" (+{} other)".format(len(rules) - 1)

    text_column = {
        "type": "Column",
        "items": [{"type": "TextBlock", "size": "Small", "weight": "Lighter", "text": text}],
        "isSubtle": True,
        "width": "auto",
        "spacing": "none",
    }

    date = group.last_seen.replace(microsecond=0).isoformat()
    date_text = "{{DATE(%s, SHORT)}} at {{TIME(%s)}}" % (date, date)
    date_column = {
        "type": "Column",
        "items": [
            {
                "type": "TextBlock",
                "size": "Small",
                "weight": "Lighter",
                "horizontalAlignment": "Center",
                "text": date_text,
            }
        ],
        "width": "auto",
        "separator": True,
    }

    return {"type": "ColumnSet", "columns": [image_column, text_column, date_column]}


def build_incident_actions(group):
    status = group.get_status()

    # These targets are made so that the button will toggle its element
    # on or off, and toggle the other elements off.
    resolve_targets = [
        {"elementId": "resolveTitle"},
        {"elementId": "resolveInput"},
        {"elementId": "resolveSubmit"},
        {"elementId": "ignoreTitle", "isVisible": False},
        {"elementId": "ignoreInput", "isVisible": False},
        {"elementId": "ignoreSubmit", "isVisible": False},
        {"elementId": "assignTitle", "isVisible": False},
        {"elementId": "assignInput", "isVisible": False},
        {"elementId": "assignSubmit", "isVisible": False},
    ]

    ignore_targets = [
        {"elementId": "resolveTitle", "isVisible": False},
        {"elementId": "resolveInput", "isVisible": False},
        {"elementId": "resolveSubmit", "isVisible": False},
        {"elementId": "ignoreTitle"},
        {"elementId": "ignoreInput"},
        {"elementId": "ignoreSubmit"},
        {"elementId": "assignTitle", "isVisible": False},
        {"elementId": "assignInput", "isVisible": False},
        {"elementId": "assignSubmit", "isVisible": False},
    ]

    assign_targets = [
        {"elementId": "resolveTitle", "isVisible": False},
        {"elementId": "resolveInput", "isVisible": False},
        {"elementId": "resolveSubmit", "isVisible": False},
        {"elementId": "ignoreTitle", "isVisible": False},
        {"elementId": "ignoreInput", "isVisible": False},
        {"elementId": "ignoreSubmit", "isVisible": False},
        {"elementId": "assignTitle"},
        {"elementId": "assignInput"},
        {"elementId": "assignSubmit"},
    ]

    if status == GroupStatus.RESOLVED:
        resolve_action = {
            "type": "Action.Submit",
            "title": "Unresolve",
            "data": {"actionType": "unresolve"},
        }
    else:
        resolve_action = {
            "type": "Action.ToggleVisibility",
            "title": "Resolve",
            "targetElements": resolve_targets,
        }

    if status == GroupStatus.IGNORED:
        ignore_action = {
            "type": "Action.Submit",
            "title": "Stop Ignoring",
            "data": {"actionType": "unignore"},
        }
    else:
        ignore_action = {
            "type": "Action.ToggleVisibility",
            "title": "Ignore",
            "targetElements": ignore_targets,
        }

    assign_text = "Assign"
    assign_action = {
        "type": "Action.ToggleVisibility",
        "title": assign_text,
        "targetElements": assign_targets,
    }

    return {
        "type": "ColumnSet",
        "columns": [
            {
                "type": "Column",
                "items": [{"type": "ActionSet", "actions": [resolve_action]}],
                "width": "stretch",
            },
            {
                "type": "Column",
                "items": [{"type": "ActionSet", "actions": [ignore_action]}],
                "width": "stretch",
            },
            {
                "type": "Column",
                "items": [{"type": "ActionSet", "actions": [assign_action]}],
                "width": "stretch",
            },
        ],
    }


def build_incident_resolve_card():
    title_card = {
        "type": "TextBlock",
        "size": "Large",
        "text": "Resolve",
        "weight": "Bolder",
        "id": "resolveTitle",
        "isVisible": False,
    }

    input_card = {
        "type": "Input.ChoiceSet",
        "value": "0",
        "id": "resolveInput",
        "isVisible": False,
        "choices": [
            {"title": "Immediately", "value": "0"},
            {"title": "In the current release", "value": "1"},
            {"title": "In the next release", "value": "2"},
        ],
    }

    submit_card = {
        "type": "ActionSet",
        "id": "resolveSubmit",
        "isVisible": False,
        "actions": [
            {"type": "Action.Submit", "title": "Resolve", "data": {"actionType": "resolve"}}
        ],
    }

    return [title_card, input_card, submit_card]


def build_incident_ignore_card():
    title_card = {
        "type": "TextBlock",
        "size": "Large",
        "text": "Ignore until this happens again...",
        "weight": "Bolder",
        "id": "ignoreTitle",
        "isVisible": False,
    }

    input_card = {
        "type": "Input.ChoiceSet",
        "value": "0",
        "id": "ignoreInput",
        "isVisible": False,
        "choices": [
            {"title": "1 time", "value": "0"},
            {"title": "10 times", "value": "1"},
            {"title": "100 times", "value": "2"},
            {"title": "1,000 times", "value": "3"},
            {"title": "10,000 times", "value": "4"},
        ],
    }

    submit_card = {
        "type": "ActionSet",
        "id": "ignoreSubmit",
        "isVisible": False,
        "actions": [{"type": "Action.Submit", "title": "Ignore", "data": {"actionType": "ignore"}}],
    }

    return [title_card, input_card, submit_card]


def build_incident_assign_card(group):
    teams = [
        {"title": u"#{}".format(u.slug), "value": u"team:{}".format(u.id)}
        for u in group.project.teams.all()
    ].sort()
    title_card = {
        "type": "TextBlock",
        "size": "Large",
        "text": "Assign to...",
        "weight": "Bolder",
        "id": "assignTitle",
        "isVisible": False,
    }

    input_card = {
        "type": "Input.ChoiceSet",
        "id": "assignInput",
        "isVisible": False,
        "choices": teams,
    }

    submit_card = {
        "type": "ActionSet",
        "id": "assignSubmit",
        "isVisible": False,
        "actions": [{"type": "Action.Submit", "title": "Assign", "data": {"actionType": "assign"}}],
    }

    return [title_card, input_card, submit_card]


def build_incident_action_cards(group):
    status = group.get_status()
    action_cards = []
    if status != GroupStatus.RESOLVED:
        action_cards += build_incident_resolve_card()
    if status != GroupStatus.IGNORED:
        action_cards += build_incident_ignore_card()
    action_cards += build_incident_assign_card(group)

    return {"type": "ColumnSet", "columns": [{"type": "Column", "items": action_cards}]}


def build_incident_card(group, event, rules):
    project = Project.objects.get_from_cache(id=group.project_id)

    title = build_incident_title(group)
    body = [title]

    desc = build_incident_desc(group)
    if desc:
        body.append(desc)

    footer = build_incident_footer(group, rules, project)
    body.append(footer)

    actions = build_incident_actions(group)
    body.append(actions)

    action_cards = build_incident_action_cards(group)
    body.append(action_cards)

    return {"type": "AdaptiveCard", "body": body}
