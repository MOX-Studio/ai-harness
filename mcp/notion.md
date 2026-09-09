# Notion MCP

Адрес: `https://mcp.notion.com/mcp`. Авторизация — личный OAuth. [Официальная инструкция](https://developers.notion.com/guides/mcp/get-started-with-mcp).

Сначала проверьте существующее подключение `notion`. Если адрес совпадает и подключение работает, используйте его. При другом адресе сохраните конфигурацию и уточните конфликт.

## Codex

```sh
codex mcp get notion
codex mcp add notion --url https://mcp.notion.com/mcp
codex mcp login notion
```

`add` нужен только при отсутствии сервера; `login` — если требуется вход.

## Claude Code

```sh
claude mcp get notion
claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp
```

`add` нужен только при отсутствии сервера. Для входа откройте `/mcp` в Claude Code.

## Проверка

Обновите подключения или начните новую сессию. Проверьте доступность инструментов Notion; если сотрудник указал страницу, проверьте её чтение. Ошибку доступа сообщите отдельно от результата установки. Настройка MCP не выдаёт права на страницы автоматически.
