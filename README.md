![lac-cli](https://raw.githubusercontent.com/iammcoding/lac-cli/main/lacicon.png)

# lac-cli

lac-cli is a terminal shell built by [lacai.io](https://lacai.io) that brings AI directly into your command line. It autocompletes what you are typing in real time and understands plain English so you can describe what you want to do instead of memorizing commands.

## Install

```bash
pip install lac-cli
```

## Getting Started

Run `lac` to launch the shell. The first time you run it, a setup wizard will walk you through picking your AI provider and entering your API key. After that it goes straight to the shell every time.

```bash
lac
```

To redo the setup at any time:

```bash
lac --setup
```

To run without an internet connection or server:

```bash
lac --offline
```

## How It Works

When you launch `lac`, it automatically starts a local server in the background that handles communication with your AI model. You do not need to start anything manually.

As you type, the shell sends your input to the AI and shows a suggested completion as ghost text. Press Tab to accept it. If you type something in plain English like "show all files bigger than 100mb", the shell converts it to the right command and asks you to confirm before running it.

## Supported Providers

| Provider | Notes |
|----------|-------|
| `claude` | Anthropic API |
| `openai` | OpenAI API |
| `ollama` | Local models, no API key needed |
| `custom` | Any OpenAI compatible endpoint |

## Commands

| Command | What it does |
|---------|--------------|
| `exit` | Quit the shell |
| `logout` | Delete your config and start fresh |
| `clear` | Clear the screen |
| `cd <path>` | Change directory |

## Config

Your config is saved at `~/.lac/config.json` after setup. You can edit it directly if needed.

```json
{
  "provider": "claude",
  "api_key": "sk-...",
  "model": "claude-haiku-4-5-20251001",
  "base_url": "https://api.anthropic.com",
  "server": "ws://localhost:8765"
}
```

## Features

- Ghost text autocomplete as you type, powered by your AI model
- Plain English to shell command conversion with confirmation before running
- Works with any major AI provider or local models via Ollama
- Offline mode falls back to history and static completions
- Local server starts automatically in the background, no manual setup needed
- Logout clears your credentials and resets the config

## About

lac-cli is part of [lacai.io](https://lacai.io). Built for developers who live in the terminal.

## License

MIT
