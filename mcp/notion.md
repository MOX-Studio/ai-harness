# Notion MCP

[Документация](https://developers.notion.com/guides/mcp/get-started-with-mcp).

1. Проверь сервер:

```sh
codex mcp get notion
```

2. Если отсутствует — добавь. При другом адресе сохрани конфигурацию и сообщи конфликт.

```sh
codex mcp add notion --url https://mcp.notion.com/mcp
```

3. Если нужен OAuth — запусти вход, который завершает пользователь:

```sh
codex mcp login notion
```

Проверь инструменты Notion. Если задана страница — проверь чтение. Отсутствие доступа укажи отдельно.
