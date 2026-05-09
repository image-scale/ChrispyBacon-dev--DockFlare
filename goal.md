# Goal

## Project
DockFlare — a python project.

## Description
DockFlare is a self-hosted ingress and access-control plane for Cloudflare Tunnel environments. It continuously translates desired state from Docker container labels into Cloudflare configuration by monitoring containers, managing tunnel ingress rules, DNS records, and Cloudflare Access applications. It provides automatic service discovery from Docker labels, manual rule management, state reconciliation, and multi-host agent support.

## Scope
- Core modules for configuration, Cloudflare API, Docker handling, tunnel management, state management
- Reconciliation engine for syncing desired vs actual state
- Web application with Flask including setup, API routes, and authentication
- Redis/memory caching support
- Backup and restore functionality
- Multi-host agent support
- Complete test coverage for all implemented functionality
