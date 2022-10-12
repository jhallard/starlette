import typing

from starlette.datastructures import State, URLPath
from starlette.middleware import Middleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Router
from starlette.types import ASGIApp, Receive, Scope, Send


class Starlette:
    """
    Creates an application instance.

    **Parameters:**

    * **debug** - Boolean indicating if debug tracebacks should be returned on errors.
    * **routes** - A list of routes to serve incoming HTTP and WebSocket requests.
    * **middleware** - A list of middleware to run for every request. A starlette
    application will always automatically include two middleware classes.
    `ServerErrorMiddleware` is added as the very outermost middleware, to handle
    any uncaught errors occurring anywhere in the entire stack.
    `ExceptionMiddleware` is added as the very innermost middleware, to deal
    with handled exception cases occurring in the routing or endpoints.
    * **exception_handlers** - A mapping of either integer status codes,
    or exception class types onto callables which handle the exceptions.
    Exception handler callables should be of the form
    `handler(request, exc) -> response` and may be be either standard functions, or
    async functions.
    * **on_startup** - A list of callables to run on application startup.
    Startup handler callables do not take any arguments, and may be be either
    standard functions, or async functions.
    * **on_shutdown** - A list of callables to run on application shutdown.
    Shutdown handler callables do not take any arguments, and may be be either
    standard functions, or async functions.
    """

    def __init__(
        self,
        debug: bool = False,
        routes: typing.Optional[typing.Sequence[BaseRoute]] = None,
        middleware: typing.Optional[typing.Sequence[Middleware]] = None,
        exception_handlers: typing.Optional[
            typing.Mapping[
                typing.Any,
                typing.Callable[
                    [Request, Exception],
                    typing.Union[Response, typing.Awaitable[Response]],
                ],
            ]
        ] = None,
        on_startup: typing.Optional[typing.Sequence[typing.Callable]] = None,
        on_shutdown: typing.Optional[typing.Sequence[typing.Callable]] = None,
        lifespan: typing.Optional[
            typing.Callable[["Starlette"], typing.AsyncContextManager]
        ] = None,
    ) -> None:
        # The lifespan context function is a newer style that replaces
        # on_startup / on_shutdown handlers. Use one or the other, not both.
        assert lifespan is None or (
            on_startup is None and on_shutdown is None
        ), "Use either 'lifespan' or 'on_startup'/'on_shutdown', not both."

        self._debug = debug
        self.state = State()
        self.router = Router(
            routes, on_startup=on_startup, on_shutdown=on_shutdown, lifespan=lifespan
        )
        self.exception_handlers = (
            {} if exception_handlers is None else dict(exception_handlers)
        )
        self.user_middleware = [] if middleware is None else list(middleware)
        self.middleware_stack = self.build_middleware_stack()

    def build_middleware_stack(self) -> ASGIApp:
        debug = self.debug
        error_handler = None
        exception_handlers: typing.Dict[
            typing.Any, typing.Callable[[Request, Exception], Response]
        ] = {}

        for key, value in self.exception_handlers.items():
            if key in (500, Exception):
                error_handler = value
            else:
                exception_handlers[key] = value

        middleware = (
            [Middleware(ServerErrorMiddleware, handler=error_handler, debug=debug)]
            + self.user_middleware
            + [
                Middleware(
                    ExceptionMiddleware, handlers=exception_handlers, debug=debug
                )
            ]
        )

        app = self.router
        for cls, options in reversed(middleware):
            app = cls(app=app, **options)
        return app

    @property
    def routes(self) -> typing.List[BaseRoute]:
        return self.router.routes

    @property
    def debug(self) -> bool:
        return self._debug

    @debug.setter
    def debug(self, value: bool) -> None:
        self._debug = value
        self.middleware_stack = self.build_middleware_stack()

    def url_path_for(self, name: str, **path_params: typing.Any) -> URLPath:
        return self.router.url_path_for(name, **path_params)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope["app"] = self
        await self.middleware_stack(scope, receive, send)
