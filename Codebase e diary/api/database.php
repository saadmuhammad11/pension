<?php
$servername = $hesk_settings['db_host'];
$username = $hesk_settings['db_user'];
$password = $hesk_settings['db_pass'];
$dbname = $hesk_settings['db_name'];

$conn = new mysqli($servername, $username, $password,$dbname);

if ($conn->connect_error) {
    echo 'ede';
    echo json_encode([
        'status'=>false,
        'messages'=> [
            "Databse connection failed: " . mysqli_connect_error()
        ]
    ]);
    exit;
}
function executeQuery($query,$conn){
    if ($conn->query($query) === TRUE) {
        echo json_encode([
            'status'=>true,
            'messages'=> [
                'Record inserted successfully'
            ]
        ]);
        exit;
    }
    else{
        echo json_encode([
            'status'=>false,
            'messages'=> [
                $conn->error
            ]
        ]);
        exit;
    }
}