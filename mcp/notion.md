# Notion MCP

[Официальная инструкция](https://developers.notion.com/guides/mcp/get-started-with-mcp).

Сначала проверьте `get`. Добавляйте только отсутствующий сервер; другой адрес не заменяйте.

## Codex

```sh
codex mcp get notion
codex mcp add notion --url https://mcp.notion.com/mcp
codex mcp login notion
```

## Claude Code

```sh
claude mcp get notion
claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp
```

Вход: `/mcp` в Claude Code. Используйте личный аккаунт.

После подключения проверьте инструменты Notion. Если задана страница — проверьте её чтение. Отсутствие доступа укажите отдельно.
