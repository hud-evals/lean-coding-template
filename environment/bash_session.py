import asyncio
import os
import tempfile

from .base import CLIResult, ToolError, ToolResult


class _BashSession:
    """A session of a bash shell."""

    _started: bool
    _process: asyncio.subprocess.Process

    command: str = "/bin/bash"
    _output_delay: float = 0.2
    _timeout: float = 30.0
    _sentinel: str = "<<exit>>"

    def __init__(self):
        self._started = False
        self._timed_out = False

    async def start(self):
        if self._started:
            await asyncio.sleep(0)
            return

        def demote():
            os.setsid()
            os.setgid(1000)
            os.setuid(1000)

        self._process = await asyncio.create_subprocess_shell(
            self.command,
            preexec_fn=demote,
            shell=True,
            bufsize=0,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._started = True

    def stop(self):
        """Terminate the bash shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return
        self._process.terminate()

    async def run(self, command: str):
        """Execute a command in the bash shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            await asyncio.sleep(0)
            return ToolResult(
                system="tool must be restarted",
                error=f"bash has exited with returncode {self._process.returncode}",
            )
        if self._timed_out:
            raise ToolError(
                f"timed out: bash has not returned in {self._timeout} seconds and must be restarted.",
            )

        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        self._process.stdin.write(command.encode() + f"; echo '{self._sentinel}'\n".encode())
        await self._process.stdin.drain()

        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    await asyncio.sleep(self._output_delay)
                    output = self._process.stdout._buffer.decode()
                    error = self._process.stderr._buffer.decode()
                    if self._sentinel in output:
                        output = output[: output.index(self._sentinel)]
                        break
        except TimeoutError:
            self._timed_out = True
            stdout_truncated = output[:10000] + "<response clipped>" if len(output) > 10000 else output
            stderr_truncated = error[:10000] + "<response clipped>" if len(error) > 10000 else error

            stdout_file = None
            stderr_file = None

            try:
                with tempfile.NamedTemporaryFile(mode='w', prefix='bash_stdout_', suffix='.log', delete=False) as f:
                    f.write(output)
                    stdout_file = f.name

                with tempfile.NamedTemporaryFile(mode='w', prefix='bash_stderr_', suffix='.log', delete=False) as f:
                    f.write(error)
                    stderr_file = f.name

                raise ToolError(
                    f"timed out: bash has not returned in {self._timeout} seconds and must be restarted.\n"
                    f"Full logs saved to:\n"
                    f"  STDOUT: {stdout_file}\n"
                    f"  STDERR: {stderr_file}\n"
                    f"Truncated output:\n"
                    f"  STDOUT: {stdout_truncated}\n"
                    f"  STDERR: {stderr_truncated}",
                ) from None
            except Exception:
                raise ToolError(
                    f"timed out: bash has not returned in {self._timeout} seconds and must be restarted. Full logs are saved to \n STDOUT: {stdout_truncated}\n STDERR: {stderr_truncated}",
                ) from None

        if output.endswith("\n"):
            output = output[:-1]

        if error.endswith("\n"):
            error = error[:-1]

        self._process.stdout._buffer.clear()
        self._process.stderr._buffer.clear()

        return CLIResult(output=output, error=error)


class BashSessionManager:
    """Manages bash sessions for the environment server."""

    _session: _BashSession | None

    def __init__(self):
        self._session = None

    async def execute(self, command: str | None = None, restart: bool = False) -> ToolResult:
        if restart:
            if self._session:
                self._session.stop()
            self._session = _BashSession()
            await self._session.start()

            return ToolResult(system="tool has been restarted.")

        if self._session is None:
            self._session = _BashSession()
            await self._session.start()

        if command is not None:
            return await self._session.run(command)

        raise ToolError("no command provided.")
