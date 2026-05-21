> This project is currently under **rapid development**. For the latest and most accurate documentation, please visit:
> **[ngdc.cncb.ac.cn/dingent](https://ngdc.cncb.ac.cn/dingent/)**
>
> 最新文档和使用指南，请访问：
> **[ngdc.cncb.ac.cn/dingent](https://ngdc.cncb.ac.cn/dingent/)**

<div align="center"><a name="readme-top"></a>

# Dingent

**A powerful, yet user-friendly LLM Agent framework designed to streamline the
entire development lifecycle of intelligent applications.**

</div>

**Dingent** is an agent framework whose core goal is to simplify the process of
creating any application powered by Large Language Models (LLMs). We provide a
concise yet powerful toolkit... to build applications capable of automating
complex workflows, interacting with various services, and performing intelligent
analysis. For any custom logic or integration, Dingent offers a flexible
framework that developers can easily extend by writing custom code.

### Chat Interface

|          Chat View 1          |          Chat View 2          |
| :---------------------------: | :---------------------------: |
| ![chat1](./assets/Chart1.png) | ![chat2](./assets/Chart2.png) |

### Admin Dashboard

|             Dashboard - Overview             |           Dashboard - Workflows            |
| :------------------------------------------: | :----------------------------------------: |
|   ![overview](./assets/admin-overview.png)   | ![workflows](./assets/admin-workflows.png) |
|           **Dashboard - Settings**           |            **Dashboard - Logs**            |
|   ![settings](./assets/admin-settings.png)   |      ![logs](./assets/admin-logs.png)      |
|          **Dashboard - Assistants**          |           **Dashboard - Market**           |
| ![assistants](./assets/admin-assistants.png) |    ![market](./assets/admin-market.png)    |

## 🎯 Why Choose Dingent?

When building LLM applications, developers often spend a significant amount of
time on "glue code": creating backend services, wrapping APIs, setting up
frontend-backend communication... These tasks are tedious and repetitive.

**Dingent's core value lies in:**

- **No More Repetition**: We package the best practices for backend services
  (LangGraph), data interfaces (**Plugin System**), a chat interface
  (CopilotKit), and a **full-featured admin dashboard** into a single command.
  You no longer need to build everything from scratch and can start writing your
  core business logic immediately.

* **Configuration via UI**: Forget manually editing complex configuration files.
  With Dingent's integrated admin dashboard, you can manage assistants, build
  workflows, and configure settings through an intuitive graphical interface.
* **Extensible and Versatile**: While Dingent began with a focus on data
  retrieval, it has evolved into a powerful general-purpose framework. Its
  modular architecture and robust plugin system allow you to build any type of
  agent—from simple task automation bots to complex multi-agent systems. Dingent
  provides the solid foundation, you bring the vision.
* **Core Features Built-In**: We believe a simple and easy-to-use agent
  shouldn't require users to spend a lot of time maintaining plugins. Therefore,
  we are committed to integrating features the community deems important
  directly into the framework. If you think a feature is crucial, we encourage
  you to open an Issue or PR. This directly reflects our core mission of "making
  Agents simpler for users."

- **Smooth Learning Curve**: You only need a basic understanding of Python to
  build powerful, general-purpose agents, without needing to be an expert in
  LangGraph or FastAPI. At the same time, we retain the flexibility to expand
  functionalities, ensuring the framework can fully support custom development
  when needed.

## ✨ Features

- **Instant Project Setup**: Simply run `dingent dev` in any directory to
  initialize a new project.
- **Integrated Admin Dashboard**: A powerful, React-based web interface to
  visually manage your assistants, workflows, plugins, and settings.
- **Bundled Frontend**: A pre-built, standalone Next.js chat interface is
  included out-of-the-box. No need for manual setup or compilation.
- **Lightweight and Easy to Use**: A clean design and a gentle learning curve
  let you focus on business logic rather than tedious configuration.
- **Guest Mode Support**: Allow unauthenticated users to chat with AI agents
  without requiring registration. See
  [Guest Mode Documentation](./GUEST_MODE.md) for details.

## 🚀 Quick Start

Just download the latest executable for your platform from the releases page and run it.


# Run the development server
uvx dingent dev # or uvx dingent run
```

The first time you run this command, Dingent will ask if you want to create a
`dingent.toml` configuration file, officially turning the directory into a
Dingent project root.

The `dev` command will start all necessary services:

- **Frontend Chat**: Accessible at
  [http://localhost:3000](http://localhost:3000)
- **Backend API**: Running at [http://localhost:8000](http://localhost:8000)
- **Admin Dashboard**: Accessible at
  [http://localhost:8000/admin](http://localhost:8000/admin)

Your project is now live\! You can now:

- **Configure your application**: Open the admin dashboard at
  `http://localhost:8000/admin` to create assistants, build workflows, and
  configure your LLM settings.
- **Add custom tools**: Place your custom MCP server plugins into the `plugins/`
  directory.
- **Interact with your agent**: Start chatting with your agent through the
  frontend at `http://localhost:3000`.

## 🐳 Docker Deployment

Dingent can also be deployed using Docker and Docker Compose for easy setup and deployment.

### Prerequisites

- **Docker**: [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose**: [Install Docker Compose](https://docs.docker.com/compose/install/)

### Quick Start with Docker

1. Clone the repository:

```bash
git clone -b Docker-Dev https://github.com/littleLice/Dingent.git
cd Dingent
```

2. Start the services using Docker Compose:

```bash
docker-compose up -d
```

This will pull the pre-built images and start both the backend and frontend services.

3. Access the services:

- **Frontend Chat**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **Admin Dashboard**: [http://localhost:8000/admin](http://localhost:8000/admin)

### Stopping the Services

To stop the services, run:

```bash
docker-compose down
```

### Rebuilding the Services

If you make changes to the code and need to rebuild the Docker images:

```bash
docker-compose up -d --build
```

## 🏛️ Project Architecture

A Dingent project has a simple and intuitive structure, managed automatically
for you:

```plaintext
my-awesome-agent/
├── 📄 dingent.toml     # Main project config (ports, model, etc.). Marks the project root.
├── 📁 config/          # Stores all application configurations managed by the dashboard.
│   ├── 📁 assistants/
│   ├── 📁 plugins/
│   └── 📁 workflows/
└── 📁 plugins/         # Directory for your custom tool plugins (e.g., MCP servers).
```

- **`dingent.toml`**: The single source of truth for your project's core
  settings. The presence of this file tells Dingent commands that they are in a
  project directory.
- **`config/`**: This directory holds the configuration for your assistants,
  plugins, and workflows. You typically won't need to edit these files manually,
  as they are managed through the **Admin Dashboard**.
- **`plugins/`**: This is where you add your own functionality. Place any
  MCP-compatible server in this directory, and Dingent will automatically
  discover and integrate it.

## 🗺️ Roadmap

- **✅ 1. Documentation & Tutorials**

  - [x] **Basic Docs:** Installation and configuration guides.
  - [x] **Core Concepts:** In-depth explanations of key features and design.
  - [ ] **Plugin Dev Guide:** How to build your own plugins.
  - [x] **End-to-End Tutorials:** Complete, step-by-step project examples.

- **✅ 2. Admin Dashboard**

  - [x] **Core UI**: Fully functional dashboard for managing assistants,
        workflows, and settings.
  - [x] **Plugin Management**: Add/remove plugins directly from the UI.
  - [x] **Advanced Workflow Editor**: Visual node-based tools for building complex
        agent behaviors and logic flow.

- **✅ 3. Plugin System**

  - [x] **Auto-Discovery**: Automatically loads plugins from the `plugins/`
        directory.
  - [ ] ~~**Plugin CLI:** Install and manage plugins via the command line.~~
        (Superseded by UI management in the Admin Dashboard)
  - [x] **Plugin Marketplace:** Discover, search, and dynamically mount community
        plugins via the dashboard.

- **✅ 4. Core Plugins**

  - [x] **Database Plugin:** Connect to mainstream databases via specialized Text2SQL engines.
  - [x] **Knowledge Base Q\&A Plugin:** Intelligent retrieval and QA using entity-enhanced RAG and vector databases.
  - [x] **Heterogeneous Integration:** Out-of-the-box support for cross-platform data sources (e.g., GenBase, iDog, BioKA).

- **✅ 5. Core Architecture & Deployment**

  - [x] **Dynamic Workflow Engine:** `GraphFactory` for zero-code, Just-In-Time (JIT) compilation of multi-agent state machines.
  - [x] **MCP Native:** Deep integration with the Model Context Protocol for decoupled, decentralized tool execution and sandboxing.
  - [x] **Zero-Config Deployment:** Heterogeneous dual-process packaging (Next.js + PyInstaller) for seamless cross-platform setup.

## 🤝 How to Contribute

We created this project to make Agents simpler for users, not to build yet
another complex development framework. Therefore, we warmly welcome and heavily
rely on community contributions to shape the future of **Dingent**.

If a feature is important to you, we strongly encourage you to discuss it by
opening a GitHub Issue or contributing code directly through a Pull Request. Our
core philosophy is that the developer community should decide which features are
built into the software, rather than leaving users to maintain their own
plugins\!

If you share our vision and wish to contribute code, please follow these steps:

1. Fork this repository.
2. Create a new feature branch (`git checkout -b feature/YourAmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push your branch to GitHub (`git push origin feature/YourAmazingFeature`).
5. Create a Pull Request and clearly describe the value of your feature.

We believe that through our collective efforts, Dingent can become a truly
powerful and "out-of-the-box" tool.

## 📄 License

This project is licensed under the [MIT License](./LICENSE).
