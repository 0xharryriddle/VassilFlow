/**
 * About VassilFlow markdown content. Inlined to avoid raw-loader dependency
 * (Turbopack cannot resolve raw-loader for .md imports).
 */
export const aboutMarkdown = `# [About VassilFlow](https://github.com/linhlln1104/VassilFlow)

> **VassilFlow Harness for Long-Horizon Agent Runs**

**VassilFlow** is a Super Agent Harness for long-horizon agent execution. It gives agents stable runtime support for sessions, runs, traces, tools, policy, approvals, memory, verification, and completion evidence.

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

For questions, bugs, or product notes, open an issue in the VassilFlow repository.

---

## License

VassilFlow is open source and distributed under the **MIT License**.

---

## Acknowledgments

VassilFlow builds on proven open-source frameworks while providing its own harness contracts, runtime paths, and product experience.

### Core Frameworks
- **[LangChain](https://github.com/langchain-ai/langchain)**: Framework support for LLM interactions and chains.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Stateful multi-agent orchestration.
- **[Next.js](https://nextjs.org/)**: Web application framework for the product surface.
`;
