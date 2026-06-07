"""External interfaces (adapters) that turn inbound traffic into Events and
deliver the agent's outbox back out. Each adapter is optional and isolated so
the core never depends on a transport.
"""
