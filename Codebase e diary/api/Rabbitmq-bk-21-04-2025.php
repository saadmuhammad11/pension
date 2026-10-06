<?php
include(__DIR__ . '/config.php');
use PhpAmqpLib\Connection\AMQPStreamConnection;
use PhpAmqpLib\Exchange\AMQPExchangeType;
use PhpAmqpLib\Message\AMQPMessage;

/**
 * CodeIgniter RabbitMQ Library
 * @package   Rabbitmq
 * @category  Libraries
 */

class Rabbitmq_client {
    /**
     * Rabbitmq connection
     * @var PhpAmqpLib\Connection\AMQPStreamConnection
     */
    public $connection;

    /**
     * Rabbitmq queue management
     * @var PhpAmqpLib\\AMQPChannel
     */
    public $channel;

    /**
     * Constructor
     *
     */
    public function __construct()
    {
        $this->initialize();
    }


    /**
     * Initialize the configuration of the Library
     * @param  array $config Overridden Configuration at runtime
     *
     * @throws
     */
    public function initialize()
    {
        $this->connection 	= new AMQPStreamConnection(HOST, PORT, USER, PASS, VHOST);
        $this->channel 		= $this->connection->channel();
    }

    /**
     * Push an element in the specified queue
	 * @param  string $queue Specified queue
     * @param  mixed(string/array)  $data Data to push
     * @param  boolean $permanent Permanent mode of the queue
     * @param  array $params Additional parameters
     * @throws Exception
     * @SuppressWarnings(PHPMD.BooleanArgumentFlag)
     */
    public function push($queue = null, $data = null, $permanent = false, $params = array())
    {
        // We declare the queue
        $this->channel->queue_declare($queue, false, $permanent, false, false, false, null, null);

        // If the information given are in an array, we convert it in json format
        $data = (is_array($data)) ? json_encode($data) : $data;

        // Create a new instance of message then push it into the selected queue
        $item = new AMQPMessage($data, $params);

        // Publish to the queue
        $this->channel->basic_publish($item, '', $queue);

    }


	public function push_exchange_topic($exchange_name=null, $exchange_topic=null, $data=null, $params = array()){
	
		$this->channel->exchange_declare($exchange_name, AMQPExchangeType::TOPIC, true, false, false);
		
        // If the information given are in an array, we convert it in json format
        $data = (is_array($data)) ? json_encode($data) : $data;

		$msg = new AMQPMessage($data, $params); 
		
		$this->channel->basic_publish($msg, $exchange_name, $exchange_topic);
		
	}



    /**
     * Get the items from the specified queue
     * @param  string $queue Specified queue
     * @param  bool $permanent Permanent mode of the queue
     * @param  array $callback Callback to treat the data
     * @param  array $params params to push the message in the queue after an exception not caught by the application
     * @throws Exception
     * @SuppressWarnings(PHPMD.BooleanArgumentFlag)
     */
    public function pull($queue = null, $permanent = false, $consumerTag='', $callback = array(), $params = array())
    {

        // Declaring the queue again
        list($queue,$message_count, $consumer_count) = $this->channel->queue_declare($queue, false, $permanent, false, false, false, null, null);
        //echo $queue.'--->'.$message_count.'--->'.$consumer_count;exit;
        // Limit the number of unacknowledged
        $this->channel->basic_qos(null, 1, null);

        // Define consuming with 'process' callback
        //$this->channel->basic_consume($queue, $consumerTag, false, false, false, false, function ($message) use ($callback, $queue, $permanent, $params) {
        if($consumer_count == 0){
			
        $this->channel->basic_consume($queue, '', false, false, false, false, function ($message) use ($callback, $queue, $permanent, $params,$message_count,$consumer_count) {
	
            try {
        //echo $consumer_count;exit;
                // Call application treatment
                $callback($message,$message_count,$consumer_count);
		        // $callback($message);

            } catch (Exception $e) {

                error_log($e->getMessage());
                $this->unlock($message);
                $this->push($queue, json_encode(json_decode($message->body)), $permanent, $params);

            } catch (Throwable $t) {

                error_log($t->getMessage());
                $this->unlock($message);
                $this->push($queue, json_encode(json_decode($message->body)), $permanent, $params);

            }
			
        });
        }else{echo "Consumer already initiated";exit;}
        // Continue the process of CLI command, waiting for others instructions
        while (count($this->channel->callbacks)) {
            //$this->channel->wait($this->config['allowed_methods'], $this->config['non_blocking'], $this->config['timeout']);
            $this->channel->wait(ALLOWED_METHODS,NON_BLOCKING,TIMEOUT);
        }
    }

    /**
     * Lock a message
     * @param PhpAmqpLib\Message\AMQPMessage $message
     */
    public function lock($message)
    {
        $this->channel->basic_nack($message->delivery_info['delivery_tag'], false, true);
    }

    /**
     * Release a message
     * @param PhpAmqpLib\Message\AMQPMessage $message
     */
    public function unlock($message)
    {
        $this->channel->basic_ack($message->delivery_info['delivery_tag']);
    }

    /**
     * Move a message from a queue to another one
     *
     * @author Romain GALLIEN <romaingallien.rg@gmail.com>
     *
     * @throws
     */
    public function move()
    {
        throw new Exception("This method does not exist");
    }

    /**
     * Delete everything in the selected queue*
     * @param  string  $queue to purge
     * @throws
     */
    public function purge($queue = null)
    {
        $this->channel->queue_purge($queue);
    }

    /**
     * Close the channel and the connection
     */
    public function __destruct()
    {
        // Close the channel
        if(!empty($this->channel)) {
            $this->channel->close();
        }

        // Close the connexion
        if(!empty($this->connection)) {
            $this->connection->close();
        }
    }
}

/* End of file Rabbitmq_client.php */
/* Location: ./application/libraries/Rabbitmq_client.php */