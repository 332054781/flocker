.. Single Source Instructions

==================================
Configuring Cluster Authentication
==================================

.. begin-body-config-authentication

Communication between the different parts of your cluster is secured and authenticated via TLS.
This guide will show you how to generate and distribute the following:

* A cluster certificate to authorize you as the cluster administrator to create new node certificates.
* A control service certificate and key file, to be copied to the machine running your control service.
  The control service certificate and key file are used to identify the control service node to any Flocker agent nodes in the cluster.
* A node certificate and key file for each of your Flocker agent nodes, which identifies the node to the control service.

.. XXX Add a diagram to illustrate the distribution of certificates across the cluster. See FLOC 3085

Prerequisites
=============

Before you begin to configure authentication for your cluster, you will need to have completed the following:

* Installed the ``flocker-cli`` on your local machine.
* Installed ``flocker-node`` on each of your nodes.
* Chosen on which of your nodes you want to host the Flocker control service.

Generating and Distributing Certificates
========================================

#. Create a directory for your certificates on all nodes.

   First you need to create a :file:`/etc/flocker` directory on each node.
   This includes the control service node, and on all the Flocker agent nodes in your cluster.

   .. prompt:: bash alice@linuxbox:~/$

      sudo mkdir /etc/flocker

   This directory is where you will place your certificates.

#. Generate your cluster certificates.

   It is the cluster certificates which allow you (as the administrator of the cluster) to create new nodes on the cluster securely.

   Using the machine on which you installed the ``flocker-cli`` package, run the following command to generate your cluster's root certificate authority, replacing ``<mycluster>`` with the name you will use to uniquely identify this cluster:

   .. prompt:: bash $

      flocker-ca initialize <mycluster>

   You should now find :file:`cluster.key` and :file:`cluster.crt` in your working directory.

   .. note:: This command creates :file:`cluster.key` and :file:`cluster.crt`.
             Please keep :file:`cluster.key` secret, as anyone who can access it will be able to control your cluster.

             The file :file:`cluster.key` should be kept only by the cluster administrator; it does not need to be copied anywhere.

#. Generate your control service certificates.

   Now that you have your cluster certificates you can generate authentication certificates for the control service and each of your Flocker agent nodes.

   With the following command you will generate the control service certificates (you will create node certificates in a later step).
   Before running the command though, you will need to note the following:

   * You should replace ``<hostname>`` with the hostname of your control service node; this hostname should match the hostname you will give to HTTP API clients.
   * The ``<hostname>`` should be a valid DNS name that HTTPS clients can resolve, as they will use it as part of TLS validation.
   * It is not recommended as an IP address for the ``<hostname>``, as it can break some HTTPS clients.

   Run the following command from the directory containing your authority certificate (as generated in Step 2):

   .. prompt:: bash $

      flocker-ca create-control-certificate <hostname>

   You should now also find :file:`control-<hostname>.key` and :file:`control-<hostname>.crt` in your working directory.

#. Copy certificates to the control service node.

   You can now copy the following files to the :file:`/etc/flocker` directory on the control service node via a secure communication medium, such as SSH, SCP or SFTP and rename the files that are now on the control service node.:

   * :file:`control-<hostname>.crt`
   * :file:`control-<hostname>.key`
   * :file:`cluster.crt` (as created by the `flocker-ca initialize` step)

   For example:

   .. prompt:: bash $

      scp control-<hostname>.crt <user>@<hostname>:
      scp control-<hostname>.key <user>@<hostname>:
      scp cluster.crt <user>@<hostname>:
      ssh <user>@<hostname> 'sudo mv control-<hostname>.crt /etc/flocker/control-service.crt'
      ssh <user>@<hostname> 'sudo mv control-<hostname>.key /etc/flocker/control-service.key'
      ssh <user>@<hostname> 'sudo mv cluster.crt /etc/flocker/cluster.crt'

   .. warning:: Only copy the file :file:`cluster.crt` to the control service and node machines, not the :file:`cluster.key` file, which must kept only by the cluster administrator.

#. Change the permissions on the control service node folder and key file.

   You will need to change the permissions on the :file:`/etc/flocker` directory, and the :file:`control-service.key` file:

   .. prompt:: bash alice@linuxbox:~/#

      sudo chmod 0700 /etc/flocker
      sudo chmod 0600 /etc/flocker/control-service.key

#. Generate node authentication certificates.

   .. note:: You will need to run the following command as many times as you have nodes.

			 For example, if you have two nodes in your cluster, you will need to run this command twice.
			 This step should be repeated on all nodes on the cluster, including the machine running the control service.

   Run the following command in the same directory containing the certificate authority files you generated in the Step 2:

   .. prompt:: bash $

      flocker-ca create-node-certificate

   This will create a :file:`.crt` file and a :file:`.key` file, which will look like:

   * :file:`8eab4b8d-c0a2-4ce2-80aa-0709277a9a7a.crt`
   * :file:`8eab4b8d-c0a2-4ce2-80aa-0709277a9a7a.key`

   The actual file names you generate in this step will vary from these, as a UUID for a node is generated to uniquely identify it on the cluster and the files produced are named with that UUID.

#. Copy certificates onto the Flocker agent node.

   You can now copy the following files to the Flocker agent node via a secure communication medium, such as SSH, SCP or SFTP:

   * Your version of :file:`8eab4b8d-c0a2-4ce2-80aa-0709277a9a7a.crt`
   * Your version of :file:`8eab4b8d-c0a2-4ce2-80aa-0709277a9a7a.key`
   * :file:`cluster.crt` (as created by the `flocker-ca initialize` step)

   For example:

   .. prompt:: bash $

      scp <yourUUID>.crt <user>@<hostname>:
      scp <yourUUID>.key <user>@<hostname>:
      scp cluster.crt root@<hostname>:

#. Move and rename the certificates.

   On the node, move the cluster and node certificates into :file:`/etc/flocker` and rename the node certificate and key to :file:`node.crt` and :file:`node.key`.

   .. prompt:: bash alice@linuxbox:~/$

      sudo mv <yourUUID>.crt /etc/flocker/node.crt
      sudo mv <yourUUID>.key /etc/flocker/node.key
      sudo mv cluster.crt /etc/flocker/cluster.crt

#. Change the permissions on the folder and key file.

   You will need to change the permissions on the :file:`/etc/flocker` directory, and the :file:`node.key` file:

   .. prompt:: bash alice@linuxbox:~/$

      sudo chmod 0700 /etc/flocker
      sudo chmod 0600 /etc/flocker/node.key

#. Repeat the node authentication steps for each node.

   If you haven't done this already, you'll need to repeat steps 7, 8, 9 and 10 for each node (including the control service node if it is acting as a Flocker agent node).

.. end-body-config-authentication
