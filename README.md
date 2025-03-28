# Vertex Project

## Overview
Vertex is a Python-based project designed to [briefly describe the purpose of the project]. This README provides an overview of the classes in the model and the technologies used in the development.

## Classes in the Model
The following are the main classes in the model:

1. **Vertex**: Represents a vertex in a graph with attributes such as `id` and `data`.
2. **Edge**: Represents an edge connecting two vertices with properties like `weight` and `direction`.
3. **Graph**: Manages the collection of vertices and edges, and provides methods for graph operations such as traversal and pathfinding.

## Technologies Used
The development of this project utilized the following technologies:

- **Programming Language**: Python 3.x
- **Frameworks/Libraries**:
  - `FastApi`
  - `SQLAchemy`
  - `Pydantic`

## Getting Started
To get started with the project, follow these steps:
1. Clone the repository.
2. Install the required dependencies using `pip install -r requirements.txt`.

## Run de app
To run the application:
1. Change directory to /app

    ```bash cd app```

2. Run uvicron to start the FastAPI app:

    ```bash uvicorn main:app```

