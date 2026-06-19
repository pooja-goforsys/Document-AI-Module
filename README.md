# Chat-with-Your-Documents (React Frontend & FastAPI Backend)

An AI-powered document chatbot that lets you chat with your own PDF documents, featuring a modern React.js frontend and a robust FastAPI backend.

[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![React](https://img.shields.io/badge/React-Frontend-blue)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-blue)](https://fastapi.tiangolo.com/)

## Overview

This project provides a local solution for interacting with PDF documents using natural language. It combines a React.js frontend for a user-friendly experience with a FastAPI backend for efficient document processing and question answering using Retrieval-Augmented Generation (RAG).

**App Showcase:**

![Chat-with-Your-Documents Screenshot](images/app.png)

*See the application in action!*

## Key Features

*   **Modern React.js Frontend:** A clean and responsive user interface.
*   **FastAPI Backend:** Handles document processing and question answering efficiently.
*   **Retrieval-Augmented Generation (RAG):** Provides accurate and context-aware answers by grounding the responses in your uploaded document.
*   **Local Document Q&A:** Ask questions and get answers based on your PDF documents, all running locally.
*   **Persistent Vector Store:** Uses FAISS (via Langchain) for efficient storage and retrieval of document embeddings.
*   **Optional Together AI Integration:** Can leverage the Together AI API (Llama 3) for enhanced language generation.  The core application can function, but the chatbot will not respond without a valid API key.

## Technology Stack

*   **Frontend:**
    *   [React.js](https://reactjs.org/)
    *   [styled-components](https://styled-components.com/)
    *   [axios](https://axios-http.com/)
    *   [react-dropzone](https://react-dropzone.js.org/)
*   **Backend:**
    *   [FastAPI](https://fastapi.tiangolo.com/)
    *   [Together AI API](https://www.together.ai/) (Optional)
    *   [Hugging Face Sentence Transformers](https://huggingface.co/sentence-transformers)
    *   [FAISS](https://github.com/facebookresearch/faiss) (via Langchain)
    *   [Langchain](https://www.langchain.com/)
    *   [Python](https://www.python.org/) 3.10+

## Prerequisites

*   [Node.js](https://nodejs.org/) and npm (Node Package Manager)
*   Python 3.10 or higher
*   (Optional) A [Together AI API key](https://www.together.ai/) (required for the chatbot to respond)

## Setup and Installation

**1. Clone the repository:**

```bash
git clone https://github.com/devcom33/Chat-with-Your-Documents.git
cd Chat-with-Your-Documents