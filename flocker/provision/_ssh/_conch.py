# Copyright ClusterHQ Inc.  See LICENSE file for details.

from __future__ import absolute_import

from functools import partial
from characteristic import attributes

from eliot import write_failure, Message, MessageType, Field

from effect import TypeDispatcher, ComposedDispatcher
from txeffect import (
    make_twisted_dispatcher,
    perform,
    deferred_performer
)

from twisted.conch.endpoints import (
    SSHCommandClientEndpoint,
    # https://twistedmatrix.com/trac/ticket/7861
    _NewConnectionHelper,
    # https://twistedmatrix.com/trac/ticket/7862
    _ReadFile, ConsoleUI,
    _CommandChannel,
)

from twisted.conch.ssh.common import NS
import twisted.conch.ssh.session as session
from twisted.conch.client.knownhosts import KnownHostsFile
from twisted.internet.defer import Deferred, inlineCallbacks, CancelledError
from twisted.internet.endpoints import UNIXClientEndpoint, connectProtocol
from twisted.internet.error import ConnectionDone
from twisted.protocols.basic import LineOnlyReceiver
from twisted.python.filepath import FilePath
import os

from ...common import loop_until, timeout
from ._model import (
    Run, Sudo, RunScript, SudoScript, Put, SudoPut, Comment, RunRemotely,
    perform_comment, perform_put, perform_sudo, perform_sudo_put,
    perform_run_script, perform_sudo_script,
)

from .._effect import dispatcher as base_dispatcher

RUN_OUTPUT_MESSAGE = MessageType(
    message_type="flocker.provision.ssh:run:output",
    fields=[
        Field.for_types(u"line", [bytes], u"The output."),
    ],
    description=u"A line of command output.",
)


def extReceived(self, ext_type, data):
    from twisted.conch.ssh.connection import EXTENDED_DATA_STDERR
    if ext_type == EXTENDED_DATA_STDERR:
        self.dataReceived(data)


@attributes([
    "deferred",
    "context",
])
class CommandProtocol(LineOnlyReceiver, object):
    """
    Protocol that logs the lines of a remote command.

    :ivar Deferred deferred: Deferred to fire when the command finishes
        If the command finished successfully, will fire with ``None``.
        Otherwise, errbacks with the reason.
    :ivar Message context: The eliot message context to log.
    """
    delimiter = b'\n'

    def connectionMade(self):
        self.transport.disconnecting = False
        # SSHCommandClientEndpoint doesn't support capturing stderr.
        # We patch the SSHChannel to interleave it.
        # https://twistedmatrix.com/trac/ticket/7893
        self.transport.extReceived = partial(extReceived, self)

    def connectionLost(self, reason):
        if reason.check(ConnectionDone):
            self.deferred.callback(None)
        else:
            self.deferred.errback(reason)

    def lineReceived(self, line):
        self.context.bind(
            message_type="flocker.provision.ssh:run:output",
            line=line,
        ).write()


class CommandChannelWithTTY(_CommandChannel):
    """
    CentOS/RHEL wants us to have a pty in order to run commands with sudo.
    Create a pty that won't be used when creating the channel.
    """
    def channelOpen(self, ignored):
        """
        Create a pty by sending a pty-req to the server
        """
        term = 'xterm'
        winSize = (25, 80, 0, 0)
        ptyReqData = session.packRequest_pty_req(term, winSize, '')
        self.conn.sendRequest(self, 'pty-req', ptyReqData)
        command = self.conn.sendRequest(
            self, 'exec', NS(self._command), wantReply=True)
        command.addCallbacks(self._execSuccess, self._execFailure)


class SSHCommandClientEndpointWithTTY(SSHCommandClientEndpoint):
    """
    Subclass that spawns a TTY when connecting.
    """
    def _executeCommand(self, connection, protocolFactory):
        """
        Given a secured SSH connection, try to execute a command in a new
        channel created on it and associate the result with a protocol from the
        given factory.

        @param connection: See L{SSHCommandClientEndpoint.existingConnection}'s
            C{connection} parameter.

        @param protocolFactory: See L{SSHCommandClientEndpoint.connect}'s
            C{protocolFactory} parameter.

        @return: See L{SSHCommandClientEndpoint.connect}'s return value.
        """

        def disconnectOnFailure(passthrough):
            # Close the connection immediately in case of cancellation, since
            # that implies user wants it gone immediately (e.g. a timeout):
            immediate = passthrough.check(CancelledError)
            self._creator.cleanupConnection(connection, immediate)
            return passthrough

        commandConnected = Deferred()
        commandConnected.addErrback(disconnectOnFailure)

        channel = CommandChannelWithTTY(
            self._creator, self._command, protocolFactory, commandConnected)
        connection.openChannel(channel)
        return commandConnected


def get_ssh_dispatcher(connection, context):
    """
    :param Message context: The eliot message context to log.
    :param connection: The SSH connection run commands on.
    """

    @deferred_performer
    def perform_run(dispatcher, intent):
        context.bind(
            message_type="flocker.provision.ssh:run",
            command=intent.log_command_filter(intent.command),
        ).write()
        endpoint = SSHCommandClientEndpointWithTTY.existingConnection(
            connection, intent.command)
        d = Deferred()
        connectProtocol(endpoint, CommandProtocol(
            deferred=d, context=context))
        return d

    return TypeDispatcher({
        Run: perform_run,
        Sudo: perform_sudo,
        RunScript: perform_run_script,
        SudoScript: perform_sudo_script,
        Put: perform_put,
        SudoPut: perform_sudo_put,
        Comment: perform_comment,
    })


def get_connection_helper(reactor, address, username, port):
    """
    Get a :class:`twisted.conch.endpoints._ISSHConnectionCreator` to connect to
    the given remote.

    :param reactor: Reactor to connect with.
    :param bytes address: The address of the remote host to connect to.
    :param bytes username: The user to connect as.
    :param int port: The port of the ssh server to connect to.

    :return _ISSHConnectionCreator:
    """
    try:
        agentEndpoint = UNIXClientEndpoint(
            reactor, os.environ["SSH_AUTH_SOCK"])
    except KeyError:
        agentEndpoint = None

    return _NewConnectionHelper(
        reactor, address, port, None, username,
        keys=None,
        password=None,
        agentEndpoint=agentEndpoint,
        knownHosts=KnownHostsFile.fromPath(FilePath("/dev/null")),
        ui=ConsoleUI(lambda: _ReadFile(b"yes")))


@deferred_performer
@inlineCallbacks
def perform_run_remotely(reactor, base_dispatcher, intent):
    connection_helper = get_connection_helper(
        reactor,
        username=intent.username, address=intent.address, port=intent.port)

    context = Message.new(
        username=intent.username, address=intent.address, port=intent.port)

    def connect():
        connection = connection_helper.secureConnection()
        connection.addErrback(write_failure)
        timeout(reactor, connection, 30)
        return connection

    connection = yield loop_until(reactor, connect)

    dispatcher = ComposedDispatcher([
        get_ssh_dispatcher(
            connection=connection,
            context=context,
        ),
        base_dispatcher,
    ])

    yield perform(dispatcher, intent.commands)

    #  Work around https://twistedmatrix.com/trac/ticket/8138 by reaching deep
    #  into a different layer and closing a leaked connection.
    if (connection.transport and
            connection.transport.instance and
            connection.transport.instance.agent):
        connection.transport.instance.agent.transport.loseConnection()
        # Set the agent to None as the agent is unusable and cleaned up at this
        # point.
        connection.transport.instance.agent = None

    yield connection_helper.cleanupConnection(
        connection, False)


def make_dispatcher(reactor):
    return ComposedDispatcher([
        TypeDispatcher({
            RunRemotely: partial(perform_run_remotely, reactor),
        }),
        make_twisted_dispatcher(reactor),
        base_dispatcher,
    ])
