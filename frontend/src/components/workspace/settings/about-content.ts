/**
 * About VassilFlow markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
export const aboutMarkdown = `# [About VassilFlow](https://github.com/linhlln1104/VassilFlow)

> **VassilFlow Harness for Long-Horizon Agent Runs**

**VassilFlow** is a Super Agent Harness for long-horizon agent execution. It focuses on stable VassilFlow-owned boundaries for sessions, runs, traces, tools, policy, approvals, memory, verification, and completion evidence while preserving a runnable agent runtime during the migration.

---

## Core Features

* **Skills & Tools**: Built-in and extensible skills make the agent runtime adaptable.
* **Sub-Agents**: Sub-agents divide complex work into focused execution paths.
* **Sandbox & File System**: Code and file operations run through controlled sandbox boundaries.
* **Context Engineering**: Isolated context and summarization keep long tasks manageable.
* **Long-Term Memory**: User profile, top-of-mind context, and conversation history can be carried forward.
* **VassilFlow Boundary Contracts**: Product-level contracts define sessions, runs, trace steps, policy decisions, approvals, and completion evidence.

---

## GitHub Repository

Explore VassilFlow on GitHub: [github.com/linhlln1104/VassilFlow](https://github.com/linhlln1104/VassilFlow)

## Support

For questions, bugs, or migration notes, open an issue in the VassilFlow repository.

---

## License

VassilFlow is open source and distributed under the **MIT License**.

---

## Acknowledgments

VassilFlow stands on a working open-source foundation and keeps clear attribution for inherited design and implementation choices while evolving its own harness contracts.

### Core Frameworks
- **[LangChain](https://github.com/langchain-ai/langchain)**: Framework support for LLM interactions and chains.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Stateful multi-agent orchestration.
- **[Next.js](https://nextjs.org/)**: Web application framework for the product surface.

### Upstream Foundation
- **[DeerFlow](https://github.com/bytedance/deer-flow)**: The upstream project that provided the initial runnable runtime foundation.
`;
