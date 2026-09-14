export class DomainValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DomainValidationError";
  }
}

export class InvalidTransitionError extends Error {
  constructor(from: string, to: string) {
    super(`Invalid task status transition: ${from} -> ${to}`);
    this.name = "InvalidTransitionError";
  }
}
